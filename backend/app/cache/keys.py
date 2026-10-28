"""Deterministic cache key generation for speech synthesis requests.

Why this module exists:
Calculates a unique, reproducible SHA-256 digest from request parameters and normalized text.
Text normalization is strictly conservative: Unicode NFC canonical composition, whitespace
collapsing, and zero-width character removal, while preserving punctuation so natural
intonation and prosodic pauses are preserved across cache hits.
"""

import hashlib
import unicodedata
import re
from app.adapters.models import TtsRequest


# Zero-width spaces, joiners, and non-joiners
ZERO_WIDTH_CHARS = re.compile(r'[\u200B-\u200D\uFEFF]')
WHITESPACE_COLLAPSE = re.compile(r'\s+')


def normalize_speech_text(text: str) -> str:
    """Normalizes text conservatively for audio caching.
    
    1. Unicode Normalization Form C (NFC).
    2. Strips zero-width characters (ZWSP, ZWJ, ZWNJ, BOM).
    3. Collapses consecutive whitespace into a single space and strips ends.
    Note: Does NOT transliterate or strip punctuation because punctuation directly
    influences TTS cadence, pitch contour, and pause duration.
    """
    normalized = unicodedata.normalize("NFC", text)
    normalized = ZERO_WIDTH_CHARS.sub("", normalized)
    normalized = WHITESPACE_COLLAPSE.sub(" ", normalized).strip()
    return normalized


def audio_key(req: TtsRequest, version_tag: str = "v1") -> str:
    """Generates a stable SHA-256 hash representing the audio request.
    
    Key layout:
    version_tag | model | voice | language | speed | sample_rate | container | normalized_text
    """
    clean_text = normalize_speech_text(req.text)
    elements = [
        version_tag,
        req.model.lower().strip(),
        req.voice.lower().strip(),
        req.language.lower().strip(),
        f"{req.speed:.2f}",
        str(req.sample_rate),
        (req.container or "wav").lower().strip(),
        clean_text
    ]
    raw_str = "|".join(elements)
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()
