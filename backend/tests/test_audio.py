"""Tests for audio header repair and playback duration."""

import struct
import pytest
from app.audio import fix_wav_header, wav_seconds
from app.adapters.fake import generate_dummy_wav


def test_fix_wav_header_replaces_placeholder():
    # Generate broken WAV with 0xFFFFFFFF placeholders in RIFF and data chunk headers
    broken_wav = generate_dummy_wav(duration_s=0.5, sample_rate=48000, broken_header=True)

    # Verify placeholder is present
    riff_size = struct.unpack_from("<I", broken_wav, 4)[0]
    data_size = struct.unpack_from("<I", broken_wav, 40)[0]
    assert riff_size == 0xFFFFFFFF
    assert data_size == 0xFFFFFFFF

    # Run repair
    repaired_wav = fix_wav_header(broken_wav)
    assert len(repaired_wav) == len(broken_wav)

    # Verify repaired values match actual byte lengths
    fixed_riff = struct.unpack_from("<I", repaired_wav, 4)[0]
    fixed_data = struct.unpack_from("<I", repaired_wav, 40)[0]
    assert fixed_riff == len(broken_wav) - 8
    assert fixed_data == len(broken_wav) - 44


def test_wav_seconds_duration():
    wav = generate_dummy_wav(duration_s=1.0, sample_rate=48000, broken_header=True)
    dur = wav_seconds(wav)
    assert 0.95 <= dur <= 1.05


def test_fix_wav_header_ignores_non_wav():
    random_bytes = b"NOT_A_WAV_HEADER_DATA_123456"
    assert fix_wav_header(random_bytes) == random_bytes
