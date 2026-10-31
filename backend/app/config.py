"""Gateway configuration and environment variable management.

Why this module exists:
Centralizes all runtime parameters, API keys, audio presets, model configurations,
and budget limits in one validated object. This guarantees that adapters, pipelines,
and tests read consistent settings and safely default to offline mock mode when keys
are missing to prevent accidental credit exhaustion on third-party APIs.
"""

import os
from pathlib import Path
from pydantic import BaseModel, Field


def _load_env_file():
    """Finds and loads the .env file from common search paths."""
    search_dirs = [
        Path.cwd(),
        Path(__file__).resolve().parent,
        Path(__file__).resolve().parent.parent,
        Path(__file__).resolve().parent.parent.parent,
    ]
    env_file = None
    for d in search_dirs:
        candidate = d / ".env"
        if candidate.is_file():
            env_file = candidate
            break

    if not env_file:
        return

    # Try python-dotenv first
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=env_file, override=False)
        return
    except ImportError:
        pass

    # Built-in fallback parser if python-dotenv is not installed
    try:
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.split("#")[0].strip().strip('"').strip("'")
                if k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


# Run env file discovery immediately on import
_load_env_file()


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
        "en-IN": "Poorvi",
        "default": "Poorvi",
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

    # Safety switch: If MOCK_APIS is explicitly set in .env / env, respect it; otherwise default to 0 if keys exist
    mock_apis: bool = Field(default_factory=lambda: os.getenv("MOCK_APIS", "0" if os.getenv("GNANI_API_KEY") else "1") in ("1", "true", "True"))

    # Semantic Cache Threshold
    semantic_threshold: float = Field(default_factory=lambda: float(os.getenv("SEMANTIC_THRESHOLD", "0.82")))


def get_config() -> GatewayConfig:
    _load_env_file()
    return GatewayConfig()
