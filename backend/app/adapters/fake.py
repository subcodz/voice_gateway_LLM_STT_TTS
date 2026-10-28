"""Offline fake adapters for TTS, STT, and LLM.

Why this module exists:
Allows end-to-end unit and integration testing without calling Gnani, Groq, or Gemini.
Simulates realistic chunked audio streaming, RIFF placeholder headers, latency delays,
and failure modes (429, 403, and mid-stream disconnections) in a deterministic,
zero-cost environment.
"""

import asyncio
import struct
from typing import AsyncIterator, List, Optional
from app.adapters.models import TtsRequest, TtsResult, TtsStats, Transcript, Msg
from app.audio import fix_wav_header


def generate_dummy_wav(duration_s: float = 0.5, sample_rate: int = 48000, broken_header: bool = False) -> bytes:
    """Generates a dummy 16-bit mono PCM WAV payload.
    
    If broken_header is True, sets RIFF and data sizes to 0xFFFFFFFF to simulate
    Gnani's streaming placeholder bug.
    """
    num_samples = int(duration_s * sample_rate)
    # 16-bit mono: 2 bytes per sample (silence = 0)
    pcm_data = b"\x00\x00" * num_samples
    data_size = len(pcm_data)
    riff_size = data_size + 36

    header = bytearray(44)
    header[0:4] = b"RIFF"
    struct.pack_into("<I", header, 4, 0xFFFFFFFF if broken_header else riff_size)
    header[8:12] = b"WAVE"
    header[12:16] = b"fmt "
    struct.pack_into("<I", header, 16, 16)       # Subchunk1Size (16 for PCM)
    struct.pack_into("<H", header, 20, 1)        # AudioFormat (1 = PCM)
    struct.pack_into("<H", header, 22, 1)        # NumChannels (1 = Mono)
    struct.pack_into("<I", header, 24, sample_rate)  # SampleRate
    struct.pack_into("<I", header, 28, sample_rate * 2)  # ByteRate
    struct.pack_into("<H", header, 32, 2)        # BlockAlign
    struct.pack_into("<H", header, 34, 16)       # BitsPerSample
    header[36:40] = b"data"
    struct.pack_into("<I", header, 40, 0xFFFFFFFF if broken_header else data_size)

    return bytes(header) + pcm_data


class FakeTtsAdapter:
    """Mock TTS adapter simulating SSE streaming and single-shot synthesis."""

    def __init__(
        self,
        delay_ms: int = 20,
        fail_with_status: Optional[int] = None,
        truncate_stream: bool = False,
        produce_broken_header: bool = True
    ):
        self.delay_ms = delay_ms
        self.fail_with_status = fail_with_status
        self.truncate_stream = truncate_stream
        self.produce_broken_header = produce_broken_header
        self.synthesize_calls = 0
        self.stream_calls = 0
        self.synthesized_chars = 0

    async def stream(
        self,
        req: TtsRequest,
        stats: Optional[TtsStats] = None,
        bucket: Optional[str] = None
    ) -> AsyncIterator[bytes]:
        self.stream_calls += 1
        self.synthesized_chars += len(req.text)

        if self.fail_with_status == 429:
            raise RuntimeError("Gnani TTS Error: HTTP 429 Rate Limit Exceeded")
        elif self.fail_with_status == 403:
            raise RuntimeError("Gnani TTS Error: HTTP 403 Out of Credits")
        elif self.fail_with_status:
            raise RuntimeError(f"Gnani TTS Error: HTTP {self.fail_with_status}")

        full_wav = generate_dummy_wav(
            duration_s=0.6,
            sample_rate=req.sample_rate,
            broken_header=self.produce_broken_header
        )
        chunk_size = 4096
        chunks = [full_wav[i:i + chunk_size] for i in range(0, len(full_wav), chunk_size)]

        t0 = asyncio.get_event_loop().time()
        for idx, chunk in enumerate(chunks):
            if self.delay_ms > 0:
                await asyncio.sleep(self.delay_ms / 1000.0)

            if stats and idx == 0:
                stats.first_chunk_ms = int((asyncio.get_event_loop().time() - t0) * 1000)

            if self.truncate_stream and idx >= 2:
                # Abruptly stop without completing stream
                break

            if stats:
                stats.chunks_count += 1
                stats.bytes_count += len(chunk)

            yield chunk

        if stats:
            stats.total_ms = int((asyncio.get_event_loop().time() - t0) * 1000)

    async def synthesize(self, req: TtsRequest, bucket: Optional[str] = None) -> TtsResult:
        self.synthesize_calls += 1
        stats = TtsStats()
        accumulated = []
        async for chunk in self.stream(req, stats, bucket=bucket):
            accumulated.append(chunk)

        repaired_wav = fix_wav_header(b"".join(accumulated))
        return TtsResult(wav=repaired_wav, text=req.text, stats=stats)


class FakeSttAdapter:
    """Mock STT adapter simulating speech-to-text transcription."""

    def __init__(self, canned_text: str = "আমার বিদ্যুৎ বিল কত?", delay_ms: int = 15):
        self.canned_text = canned_text
        self.delay_ms = delay_ms
        self.calls = 0

    async def transcribe(self, wav: bytes, lang: str = "bn-IN") -> Transcript:
        self.calls += 1
        if self.delay_ms > 0:
            await asyncio.sleep(self.delay_ms / 1000.0)
        return Transcript(text=self.canned_text, language=lang, confidence=0.98)


class FakeLlmAdapter:
    """Mock LLM adapter simulating fast and heavy reasoning tiers."""

    def __init__(self, delay_ms: int = 25, fail_fast_tier: bool = False):
        self.delay_ms = delay_ms
        self.fail_fast_tier = fail_fast_tier
        self.calls: List[dict] = []

    async def reply(self, history: List[Msg], tier: str = "fast") -> str:
        self.calls.append({"history": history, "tier": tier})

        if tier == "fast" and self.fail_fast_tier:
            raise RuntimeError("Fast LLM simulated 429/timeout failure.")

        if self.delay_ms > 0:
            await asyncio.sleep(self.delay_ms / 1000.0)

        # Context-aware synthetic replies
        last_msg = history[-1].content if history else ""
        if "বিল" in last_msg or "bill" in last_msg.lower():
            return "আপনার চলতি মাসের বিদ্যুৎ বিল ₹১,২৪০। এটি ১৫ তারিখের মধ্যে পরিশোধ করুন।"
        elif "बिजली" in last_msg or "power" in last_msg.lower():
            return "आपके क्षेत्र में बिजली आपूर्ति शाम ६ बजे तक बहाल कर दी जाएगी।"
        else:
            return "নমস্কার, কলকাতা বিদ্যুৎ হেল্পলাইনে আপনাকে স্বাগতম। আমি কীভাবে সাহায্য করতে পারি?"
