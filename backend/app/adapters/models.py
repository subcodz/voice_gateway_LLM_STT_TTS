"""Data contracts and schemas for speech synthesis, transcription, and LLM adapters.

Why this module exists:
Provides standard typed contracts for requests, responses, audio statistics,
and conversational messages. This guarantees interoperability between real and fake
adapters, ensuring the pipeline and caches interact with stable data structures.
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class TtsStats(BaseModel):
    first_chunk_ms: int = 0
    total_ms: int = 0
    chunks_count: int = 0
    retries: int = 0
    bytes_count: int = 0


class TtsRequest(BaseModel):
    text: str
    voice: str = "Nalini"
    model: str = "timbre-v2.5"
    language: str = "hi-IN"
    speed: float = 1.0
    sample_rate: int = 48000
    container: str = "wav"


class TtsResult(BaseModel):
    wav: bytes
    text: str
    stats: TtsStats = Field(default_factory=TtsStats)

    model_config = {"arbitrary_types_allowed": True}


class Transcript(BaseModel):
    text: str
    language: str = "hi-IN"
    confidence: float = 1.0


class Msg(BaseModel):
    role: str  # 'system', 'user', 'assistant'
    content: str
