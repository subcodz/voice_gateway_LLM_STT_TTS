"""Tests for cache keys, multi-tier audio storage, and eviction rules."""

import os
import pytest
from app.adapters.models import TtsRequest
from app.cache.keys import audio_key, normalize_speech_text
from app.cache.audio_store import AudioStore


def test_normalization_and_key_stability():
    # Zero-width spaces, leading/trailing whitespace, and internal excess whitespace
    text1 = "  নমস্কার\u200B, বিদ্যুৎ   বিভাগে স্বাগতম।  "
    text2 = "নমস্কার, বিদ্যুৎ বিভাগে স্বাগতম।"
    assert normalize_speech_text(text1) == normalize_speech_text(text2)

    req1 = TtsRequest(text=text1, voice="Kirra", language="bn-IN")
    req2 = TtsRequest(text=text2, voice="Kirra", language="bn-IN")
    assert audio_key(req1) == audio_key(req2)


def test_key_separation_by_voice_language_speed_samplerate():
    base_req = TtsRequest(text="Hello", voice="Kirra", language="bn-IN", speed=1.0, sample_rate=48000)

    # Different voice
    req_voice = base_req.model_copy(update={"voice": "Nalini"})
    assert audio_key(base_req) != audio_key(req_voice)

    # Different language
    req_lang = base_req.model_copy(update={"language": "hi-IN"})
    assert audio_key(base_req) != audio_key(req_lang)

    # Different speed
    req_speed = base_req.model_copy(update={"speed": 1.1})
    assert audio_key(base_req) != audio_key(req_speed)

    # Different sample rate
    req_rate = base_req.model_copy(update={"sample_rate": 24000})
    assert audio_key(base_req) != audio_key(req_rate)

    # Version tag bumping invalidates key
    assert audio_key(base_req, version_tag="v1") != audio_key(base_req, version_tag="v2")


def test_audio_store_put_and_get(tmp_path):
    store = AudioStore(cache_dir=str(tmp_path / "cache"), l1_max_bytes=10000, l2_max_bytes=50000)
    key = "sample_key_123"
    sample_wav = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"

    assert store.get(key) is None
    store.put(key, sample_wav)

    # L1 Memory Hit
    cached = store.get(key)
    assert cached == sample_wav

    # Test persistence by instantiating new store on same disk directory
    store2 = AudioStore(cache_dir=str(tmp_path / "cache"), l1_max_bytes=10000, l2_max_bytes=50000)
    assert store2.get(key) == sample_wav


def test_lru_byte_bound_eviction(tmp_path):
    # Cap disk at 250 bytes
    store = AudioStore(cache_dir=str(tmp_path / "cache_lru"), l1_max_bytes=100, l2_max_bytes=250)

    clip_a = b"A" * 100
    clip_b = b"B" * 100
    clip_c = b"C" * 100

    store.put("key_a", clip_a)
    store.put("key_b", clip_b)
    assert store.get("key_a") is not None
    assert store.get("key_b") is not None

    # Adding clip_c (100 bytes) pushes total to 300 > 250 -> evicts least recently used
    store.put("key_c", clip_c)
    assert store.get("key_c") is not None
    # Either key_a or oldest was evicted
    assert (store.get("key_a") is None) or (store.get("key_b") is None)


def test_atomic_write_no_partial_corruptions(tmp_path):
    cache_dir = tmp_path / "atomic_cache"
    store = AudioStore(cache_dir=str(cache_dir))

    # Empty payload is never written
    store.put("empty_key", b"")
    assert store.get("empty_key") is None
    assert not os.path.exists(cache_dir / "empty_key.wav")
