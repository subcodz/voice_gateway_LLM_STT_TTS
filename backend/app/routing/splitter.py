"""Clause splitter for streaming text segmentation and pause detection.

Why this module exists:
Splits multi-sentence replies into distinct clauses using punctuation and Indic dandas.
Synthesizing and streaming the first clause immediately drops the perceived latency
(Time-To-First-Audio) to under 200ms when cached, while subsequent clauses stream or
synthesize in parallel before the caller finishes hearing the first clause.
"""

import re
from typing import List


# Punctuation marks indicating major sentence boundaries in English and Indic scripts
# Danda (। \u0964) and Double Danda (॥ \u0965)
SPLIT_REGEX = re.compile(r'([.?!।॥]+(?:\s+|$))')
CLAUSE_CAP = 120  # Max character length before looking for soft pause


def split_into_clauses(text: str, max_clause_len: int = CLAUSE_CAP) -> List[str]:
    """Splits a response into clean, vocalizable clauses.
    
    1. Splits on major delimiters: . ? ! । (danda) ॥ (double danda).
    2. Keeps punctuation attached to the preceding clause so TTS preserves intonation.
    3. If any clause exceeds max_clause_len, splits at soft natural pauses (, ; or space).
    """
    if not text or not text.strip():
        return []

    raw_tokens = SPLIT_REGEX.split(text.strip())
    clauses: List[str] = []
    current = ""

    for token in raw_tokens:
        if not token:
            continue
        if SPLIT_REGEX.match(token):
            current += token.strip()
            if current:
                clauses.append(current)
            current = ""
        else:
            current = token.strip()

    if current:
        clauses.append(current)

    # Subdivide overlong clauses at soft pauses (, ; or space) if needed
    result: List[str] = []
    for c in clauses:
        if len(c) <= max_clause_len:
            result.append(c)
        else:
            # Subdivide at comma or semicolon
            sub_parts = re.split(r'([,;]\s+)', c)
            sub_accum = ""
            for sp in sub_parts:
                if len(sub_accum) + len(sp) > max_clause_len and sub_accum:
                    result.append(sub_accum.strip())
                    sub_accum = sp
                else:
                    sub_accum += sp
            if sub_accum.strip():
                result.append(sub_accum.strip())

    return [c.strip() for c in result if c.strip()]
