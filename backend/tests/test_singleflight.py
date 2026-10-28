"""Tests for single-flight concurrency deduplication."""

import asyncio
import pytest
from app.adapters.fake import FakeTtsAdapter
from app.adapters.models import TtsRequest
from app.cache.singleflight import SingleFlight


@pytest.mark.asyncio
async def test_10_concurrent_identical_requests_cause_one_tts_call():
    sf = SingleFlight()
    fake_tts = FakeTtsAdapter(delay_ms=20)
    req = TtsRequest(text="আমাদের এলাকায় বিদ্যুৎ বিভ্রাট হয়েছে।", voice="Kirra", language="bn-IN")
    key = "dedup_test_key"

    async def _worker():
        chunks = []
        async for chunk in sf.execute_or_follow(key, lambda: fake_tts.stream(req)):
            chunks.append(chunk)
        return b"".join(chunks)

    # Launch 10 concurrent workers
    tasks = [_worker() for _ in range(10)]
    results = await asyncio.gather(*tasks)

    # All 10 callers must have received identical valid audio payloads
    assert len(results) == 10
    first_result = results[0]
    for res in results:
        assert res == first_result
        assert len(res) > 0

    # Exactly 1 TTS stream call was executed by the leader!
    assert fake_tts.stream_calls == 1
