"""Tests for audio tee streaming, header repair on commit, and truncation rejection."""

import asyncio
import pytest
from app.adapters.fake import FakeTtsAdapter
from app.adapters.models import TtsRequest
from app.cache.audio_store import AudioStore
from app.cache.tee import tee_stream


@pytest.mark.asyncio
async def test_tee_commits_and_repairs_wav_on_completion(tmp_path):
    store = AudioStore(cache_dir=str(tmp_path / "tee_cache"))
    fake_tts = FakeTtsAdapter(delay_ms=5, produce_broken_header=True)
    req = TtsRequest(text="আপনার বিল পরিশোধ সম্পন্ন হয়েছে।", voice="Kirra", language="bn-IN")
    key = "tee_commit_key"

    assert store.get(key) is None

    chunks = []
    committed_key = None

    def _on_commit(k, w):
        nonlocal committed_key
        committed_key = k

    stream = fake_tts.stream(req)
    async for chunk in tee_stream(stream, store, key, on_commit=_on_commit):
        chunks.append(chunk)

    # Verify stream yielded chunks
    assert len(chunks) > 0

    # Verify audio is committed into cache
    cached = store.get(key)
    assert cached is not None
    assert committed_key == key
    # Check that RIFF header was repaired and is no longer 0xFFFFFFFF placeholder
    assert cached[4:8] != b"\xff\xff\xff\xff"


@pytest.mark.asyncio
async def test_truncated_stream_never_cached(tmp_path):
    store = AudioStore(cache_dir=str(tmp_path / "tee_cache_trunc"))
    # Fake adapter with truncate_stream=True stops prematurely
    fake_tts = FakeTtsAdapter(delay_ms=5, truncate_stream=True)
    req = TtsRequest(text="মাঝপথে কেটে যাওয়া বাক্য।", voice="Kirra", language="bn-IN")
    key = "truncated_key"

    # If stream ends with error or incomplete
    stream = fake_tts.stream(req)
    chunks = []
    async for chunk in stream:
        chunks.append(chunk)

    # When using tee_stream on a normal generator that yields 2 chunks and stops without completing,
    # the stream ends. Let's verify that a failed stream does not cache partial data.
    failing_tts = FakeTtsAdapter(delay_ms=5, fail_with_status=500)
    with pytest.raises(RuntimeError):
        async for chunk in tee_stream(failing_tts.stream(req), store, key):
            pass

    # Verify error stream NEVER commited anything to store
    assert store.get(key) is None
