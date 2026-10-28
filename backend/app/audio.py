"""Audio utilities for WAV inspection, duration calculation, and header repair.

Why this module exists:
Gnani TTS returns streaming WAV files where the RIFF chunk size and data chunk size
are set to 0xFFFFFFFF (a streaming placeholder). Standard audio decoders, HTML5 audio
players, and Python's wave module misinterpret this placeholder as lasting over 12 hours.
This module scans the binary chunks and rewrites the header sizes with exact byte counts
so every audio clip is standard-compliant and accurately playable.
"""

import io
import struct
import wave


def fix_wav_header(wav: bytes) -> bytes:
    """Rewrite RIFF and data chunk sizes that a streamed WAV leaves as 0xFFFFFFFF.
    
    Navigates through standard RIFF chunk structure:
    - Bytes 0-4: "RIFF"
    - Bytes 4-8: File size - 8
    - Bytes 8-12: "WAVE"
    - Sequential subchunks: [4-byte ID][4-byte size (little-endian uint32)][payload...]
    """
    if len(wav) < 12 or wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        return wav

    pos = 12
    out = bytearray(wav)
    data_found = False

    while pos + 8 <= len(wav):
        cid = wav[pos:pos + 4]
        size = struct.unpack_from("<I", wav, pos + 4)[0]

        if cid == b"data":
            data_found = True
            # Patch RIFF chunk size: entire file length - 8 bytes
            struct.pack_into("<I", out, 4, len(wav) - 8)
            # Patch data chunk size: remaining payload after this 8-byte chunk header
            actual_data_size = len(wav) - (pos + 8)
            struct.pack_into("<I", out, pos + 4, actual_data_size)
            return bytes(out)

        # Move to next subchunk, accounting for word alignment padding
        pos += 8 + size + (size & 1)

    # Fallback if no explicit data chunk was encountered properly
    if not data_found and len(wav) >= 44:
        struct.pack_into("<I", out, 4, len(wav) - 8)
        struct.pack_into("<I", out, 40, len(wav) - 44)
        return bytes(out)

    return wav


def wav_seconds(wav: bytes) -> float:
    """Calculate the precise playback duration in seconds of a WAV file.
    
    Repairs the header before parsing with wave.open to ensure accurate frame count.
    """
    repaired = fix_wav_header(wav)
    try:
        with wave.open(io.BytesIO(repaired), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            return round(frames / float(rate), 3) if rate > 0 else 0.0
    except Exception:
        # Fallback approximation for 48kHz, 16-bit mono (2 bytes/sample)
        if len(wav) > 44:
            return round((len(wav) - 44) / (48000 * 2), 3)
        return 0.0
