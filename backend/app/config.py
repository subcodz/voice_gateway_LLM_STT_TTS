"""Gateway configuration and environment variable management.

Why this module exists:
Centralizes all runtime parameters, API keys, audio presets, model configurations,
and budget limits in one validated object. This guarantees that adapters, pipelines,
and tests read consistent settings and safely default to offline mock mode to prevent
accidental credit exhaustion on third-party APIs.
"""

import os
from pydantic import BaseModel, Field


class GatewayConfig(BaseModel):
    # Gnani API configuration
    gnani_api_key: str = Field(default_factory=lambda: os.getenv("GNANI_API_KEY", ""))
    gnani_base_url: str = Field(default_factory=lambda: os.getenv("GNANI_BASE_URL", "https://api.vachana.ai"))
    gnani_tts_model: str = Field(default_factory=lambda: os.getenv("GNANI_TTS_MODEL", "timbre-v2.5"))
    gnani_sample_rate: int = Field(default_factory=lambda: int(os.getenv("GNANI_SAMPLE_RATE", "48000")))

    # Verified Voices for timbre-v2.5
    voice_map: dict[str, str] = Field(default_factory=lambda: {
        "hi-IN": "Nalini",
        "bn-IN": "Kirra",
        "hi-en": "Poorvi",
    })

    # Groq configuration
    groq_api_key: str = Field(default_factory=lambda: os.getenv("GROQ_API_KEY", ""))
    groq_fast_model: str = Field(default_factory=lambda: os.getenv("GROQ_FAST_MODEL", "llama-3.1-8b-instant"))
    groq_heavy_model: str = Field(default_factory=lambda: os.getenv("GROQ_HEAVY_MODEL", "llama-3.3-70b-versatile"))

    # Gemini fallback configuration
    gemini_api_key: str = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = Field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))

    # Caching and storage settings
    version_tag: str = "v1"
    cache_dir: str = Field(default_factory=lambda: os.getenv("AUDIO_CACHE_DIR", "audio_cache"))
    cache_max_bytes: int = Field(default_factory=lambda: int(os.getenv("CACHE_MAX_BYTES", str(256 * 1024 * 1024))))  # 256MB
    l1_max_bytes: int = 64 * 1024 * 1024  # 64MB memory LRU
    finish_on_disconnect: bool = True  # tee behavior: finish synthesis if followers or for cache warmth

    # Budget & Metrics
    db_path: str = Field(default_factory=lambda: os.getenv("BUDGET_DB_PATH", "metrics.db"))
    chars_per_credit: int = 300  # Conservative estimate (actual is ~370)

    # Public Demo Guardrails
    max_chars_per_request: int = 300
    max_chars_per_session: int = 600
    max_chars_per_ip_day: int = 1500
    kill_switch: bool = Field(default_factory=lambda: os.getenv("KILL_SWITCH", "0") in ("1", "true", "True"))

    # Safety switch: Mock mode ensures tests and local dev NEVER call paid endpoints
    mock_apis: bool = Field(default_factory=lambda: os.getenv("MOCK_APIS", "1") in ("1", "true", "True"))

    # Semantic Cache Threshold
    semantic_threshold: float = 0.82


def get_config() -> GatewayConfig:
    return GatewayConfig()
