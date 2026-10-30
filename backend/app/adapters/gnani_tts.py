"""Production Gnani TTS adapter with SSE streaming, header repair, and budget enforcement.

Why this module exists:
Interfaces with Gnani's speech synthesis API (SSE streaming and REST inference endpoints).
It parses asynchronous server-sent events, decodes base64 audio chunks, enforces budget
pre-reservation to prevent credit overages, retries transient 429/5xx errors before audio starts,
and automatically repairs WAV headers using app.audio.fix_wav_header.
"""

import asyncio
import base64
import json
import time
from typing import AsyncIterator, Optional
import httpx

from app.adapters.models import TtsRequest, TtsResult, TtsStats
from app.audio import fix_wav_header
from app.budget import BudgetTracker


class TtsIncomplete(Exception):
    """Raised when an SSE audio stream terminates before receiving a completion event."""
    pass


class TtsTransient(Exception):
    """Gnani sent a retryable error event inside the SSE stream."""
    pass


class GnaniTtsAdapter:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.vachana.ai",
        client: Optional[httpx.AsyncClient] = None,
        budget_tracker: Optional[BudgetTracker] = None,
        default_bucket: str = "dev_listening",
        kill_switch: bool = False
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=60.0)
        self.budget_tracker = budget_tracker
        self.default_bucket = default_bucket
        self.kill_switch = kill_switch

    def _headers(self) -> dict[str, str]:
        return {
            "X-API-Key-ID": self.api_key,
            "Content-Type": "application/json"
        }

    def _payload(self, req: TtsRequest) -> dict:
        lang = req.language
        if lang in ("hi-en", "default"):
            lang = "en-IN"

        return {
            "text": req.text,
            "voice": req.voice,
            "model": req.model,
            "language": lang,
            "speed": req.speed,
            "audio_config": {
                "sample_rate": req.sample_rate,
                "num_channels": 1,
                "sample_width": 2,
                "encoding": "linear_pcm",
                "container": req.container or "wav"
            }
        }

    async def stream(
        self,
        req: TtsRequest,
        stats: Optional[TtsStats] = None,
        bucket: Optional[str] = None
    ) -> AsyncIterator[bytes]:
        """Streams audio chunks via Gnani's SSE endpoint with backoff retry before first byte."""
        target_bucket = bucket or self.default_bucket
        chars_count = len(req.text)

        # Enforce budget reservation before calling the API
        if self.budget_tracker:
            self.budget_tracker.reserve(target_bucket, chars_count, kill_switch=self.kill_switch)

        url = f"{self.base_url}/api/v1/tts/sse"
        payload = self._payload(req)
        retries = 0
        max_retries = 3
        backoff = 0.5
        t0 = time.perf_counter()
        completed = False
        yielded_any = False

        try:
            while True:
                try:
                    async with self.client.stream(
                        "POST",
                        url,
                        headers=self._headers(),
                        json=payload,
                        timeout=60.0
                    ) as response:
                        if response.status_code == 403:
                            raise RuntimeError("Gnani TTS 403: Out of credits or forbidden. Never retrying 403.")
                        
                        if response.status_code in (429, 500, 502, 503, 504):
                            if yielded_any or retries >= max_retries:
                                response.raise_for_status()
                            retries += 1
                            if stats:
                                stats.retries = retries
                            await asyncio.sleep(backoff)
                            backoff *= 2.0
                            continue

                        if response.status_code >= 400:
                            body = (await response.aread()).decode("utf-8", "replace")[:500]
                            raise RuntimeError(f"Gnani TTS {response.status_code}: {body}")

                        event = None
                        data_lines = []

                        async for line in response.aiter_lines():
                            if line is None:
                                continue
                            line = line.strip()

                            if not line:
                                if event or data_lines:
                                    full_data = "\n".join(data_lines)
                                    parsed = {}
                                    if full_data:
                                        try:
                                            parsed = json.loads(full_data)
                                        except json.JSONDecodeError:
                                            pass

                                    if event == "error":
                                        code = parsed.get("status_code", 0) if isinstance(parsed, dict) else 0
                                        if code in (429, 500, 502, 503, 504):
                                            raise TtsTransient(full_data)
                                        raise RuntimeError(f"Gnani TTS error event: {full_data}")

                                    if event == "chunk" and parsed.get("audio"):
                                        raw_chunk = base64.b64decode(parsed["audio"])
                                        if not yielded_any and stats:
                                            stats.first_chunk_ms = round((time.perf_counter() - t0) * 1000)
                                        yielded_any = True
                                        if stats:
                                            stats.chunks_count += 1
                                            stats.bytes_count += len(raw_chunk)
                                        yield raw_chunk

                                    if event == "complete" or parsed.get("is_final"):
                                        completed = True
                                        break

                                event = None
                                data_lines = []
                            elif line.startswith("event:"):
                                event = line[6:].strip()
                            elif line.startswith("data:"):
                                data_lines.append(line[5:].strip())

                        if not completed and not yielded_any and retries < max_retries:
                            # Stream died before any chunk; retry
                            retries += 1
                            if stats:
                                stats.retries = retries
                            await asyncio.sleep(backoff)
                            backoff *= 2.0
                            continue

                        break

                except (httpx.RequestError, httpx.HTTPStatusError, TtsTransient) as exc:
                    if yielded_any or retries >= max_retries:
                        raise
                    retries += 1
                    if stats:
                        stats.retries = retries
                    await asyncio.sleep(backoff)
                    backoff *= 2.0

            if not completed:
                raise TtsIncomplete("Gnani TTS SSE stream ended without a complete event.")

        except Exception:
            # Refund reserved characters if no audio was yielded at all
            if not yielded_any and self.budget_tracker:
                self.budget_tracker.refund(target_bucket, chars_count)
            raise
        finally:
            if stats:
                stats.total_ms = round((time.perf_counter() - t0) * 1000)

    async def synthesize(
        self,
        req: TtsRequest,
        bucket: Optional[str] = None
    ) -> TtsResult:
        """Synthesizes complete audio clip using REST inference and repairs the header."""
        target_bucket = bucket or self.default_bucket
        chars_count = len(req.text)

        if self.budget_tracker:
            self.budget_tracker.reserve(target_bucket, chars_count, kill_switch=self.kill_switch)

        url = f"{self.base_url}/api/v1/tts/inference"
        t0 = time.perf_counter()
        stats = TtsStats()

        try:
            r = await self.client.post(url, headers=self._headers(), json=self._payload(req), timeout=60.0)
            if r.status_code == 403:
                raise RuntimeError("Gnani TTS 403: Out of credits. Never retrying 403.")
            r.raise_for_status()

            raw_wav = r.content
            repaired_wav = fix_wav_header(raw_wav)

            stats.total_ms = round((time.perf_counter() - t0) * 1000)
            stats.first_chunk_ms = stats.total_ms
            stats.chunks_count = 1
            stats.bytes_count = len(repaired_wav)

            return TtsResult(wav=repaired_wav, text=req.text, stats=stats)
        except Exception:
            if self.budget_tracker:
                self.budget_tracker.refund(target_bucket, chars_count)
            raise
