"""Gnani STT speech recognition adapter.

Why this module exists:
Handles multipart audio uploads to Gnani's `/stt/v3` transcription endpoint.
Translates caller spoken audio (16 kHz mono WAV) into text transcripts with
language tagging, ensuring seamless integration into the conversational router.
"""

import time
from typing import Optional
import httpx

from app.adapters.models import Transcript
from app.budget import BudgetTracker


class GnaniSttAdapter:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.vachana.ai",
        client: Optional[httpx.AsyncClient] = None,
        budget_tracker: Optional[BudgetTracker] = None,
        bucket: str = "stt_testing",
        kill_switch: bool = False
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=60.0)
        self.budget_tracker = budget_tracker
        self.bucket = bucket
        self.kill_switch = kill_switch

    async def transcribe(self, wav: bytes, lang: str = "bn-IN") -> Transcript:
        """Transcribes PCM WAV audio via Gnani STT v3."""
        # Normalize language code for Gnani STT API
        stt_lang = lang
        if stt_lang in ("hi-en", "default"):
            stt_lang = "hi-IN"

        # Calculate duration in minutes for budget accounting (approx 300 chars equiv)
        approx_chars = max(10, int(len(wav) / (16000 * 2) * 20))
        if self.budget_tracker:
            self.budget_tracker.reserve(self.bucket, approx_chars, kill_switch=self.kill_switch)

        url = f"{self.base_url}/stt/v3"
        headers = {"X-API-Key-ID": self.api_key}
        files = {"audio_file": ("caller_audio.wav", wav, "audio/wav")}
        data = {"language_code": stt_lang, "format": "transcribe"}

        try:
            r = await self.client.post(url, headers=headers, files=files, data=data, timeout=60.0)
            if r.status_code == 403:
                raise RuntimeError("Gnani STT 403: Out of credits or forbidden.")
            r.raise_for_status()

            body = r.json()
            # Handle all possible response schemas from Gnani STT
            text = ""
            if isinstance(body, dict):
                text = (
                    body.get("transcript")
                    or body.get("text")
                    or body.get("result")
                    or body.get("asr_output")
                    or body.get("transcription")
                    or ""
                )
                if not text and "data" in body:
                    data_field = body["data"]
                    if isinstance(data_field, dict):
                        text = (
                            data_field.get("transcript")
                            or data_field.get("text")
                            or data_field.get("asr_output")
                            or data_field.get("transcription")
                            or ""
                        )
                    elif isinstance(data_field, list) and len(data_field) > 0:
                        first = data_field[0]
                        if isinstance(first, dict):
                            text = first.get("transcript") or first.get("text") or first.get("asr_output") or ""
                        elif isinstance(first, str):
                            text = first
                    elif isinstance(data_field, str):
                        text = data_field
            elif isinstance(body, str):
                text = body

            return Transcript(text=text.strip(), language=lang, confidence=0.95)
        except Exception:
            if self.budget_tracker:
                self.budget_tracker.refund(self.bucket, approx_chars)
            raise
