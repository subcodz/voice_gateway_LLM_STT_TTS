"""FastAPI application entrypoint for the Gnani Voice Gateway session demo.

Why this module exists:
Builds the shared components once at startup (budget tracker, audio store, semantic
cache, router, adapters, session pipeline), hands them to the session API, and serves
the static assets. The session demo is the only view: GET / redirects to /session.

Spend protection lives in two places: the per-request, per-session and per-IP caps in
app.session_api, and the BudgetTracker buckets behind GnaniTtsAdapter (the hard backstop).
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import session_api
from app.adapters.fake import FakeLlmAdapter, FakeTtsAdapter
from app.adapters.gnani_tts import GnaniTtsAdapter
from app.adapters.llm import LlmAdapter
from app.budget import BudgetTracker
from app.cache.audio_store import AudioStore
from app.cache.semantic import SemanticCache
from app.config import GatewayConfig, get_config
from app.pipeline.session import SessionPipeline, SessionResponseCache, SessionStore
from app.routing.intents import IntentCatalog
from app.routing.router import Router

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("main")


class AppState:
    """Shared components, built once in lifespan and read by the routes."""

    config: GatewayConfig
    budget_tracker: BudgetTracker
    audio_store: AudioStore
    semantic_cache: SemanticCache
    intent_catalog: IntentCatalog
    router: Router
    tts_adapter: object
    llm_adapter: object
    session_store: SessionStore
    session_pipeline: SessionPipeline


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_config()
    state.config = cfg
    state.budget_tracker = BudgetTracker(db_path=cfg.db_path)
    state.audio_store = AudioStore(
        cache_dir=cfg.cache_dir,
        l1_max_bytes=cfg.l1_max_bytes,
        l2_max_bytes=cfg.cache_max_bytes,
    )

    # Semantic cache: load the embedder off the event loop, then seed from intents.yaml
    state.semantic_cache = SemanticCache(threshold=cfg.semantic_threshold)
    await asyncio.to_thread(state.semantic_cache.warmup)
    state.intent_catalog = IntentCatalog(yaml_path="data/intents.yaml")
    state.intent_catalog.populate_semantic_cache(state.semantic_cache)
    state.router = Router(state.intent_catalog, state.semantic_cache)

    # Fake adapters in mock mode so nothing can spend live credits by accident
    if cfg.mock_apis or not cfg.gnani_api_key:
        state.tts_adapter = FakeTtsAdapter(delay_ms=25)
        state.llm_adapter = FakeLlmAdapter(delay_ms=30)
    else:
        state.tts_adapter = GnaniTtsAdapter(
            api_key=cfg.gnani_api_key,
            base_url=cfg.gnani_base_url,
            budget_tracker=state.budget_tracker,
            default_bucket="public_demo",
            kill_switch=cfg.kill_switch,
        )
        state.llm_adapter = LlmAdapter(
            groq_api_key=cfg.groq_api_key,
            gemini_api_key=cfg.gemini_api_key,
            groq_fast_model=cfg.groq_fast_model,
            groq_heavy_model=cfg.groq_heavy_model,
            gemini_model=cfg.gemini_model,
        )

    # Session demo: one LLM layer, two TTS paths, per-session cache namespace
    state.session_store = SessionStore(
        make_cache=lambda: SessionResponseCache(
            state.semantic_cache, threshold=cfg.session_semantic_threshold
        ),
        ttl_s=cfg.session_ttl_s,
    )
    state.session_pipeline = SessionPipeline(
        llm_adapter=state.llm_adapter,
        tts_adapter=state.tts_adapter,
        audio_store=state.audio_store,
        router=state.router,
        voice_map=cfg.voice_map,
        model=cfg.gnani_tts_model,
        sample_rate=cfg.gnani_sample_rate,
        version_tag=cfg.version_tag,
        bucket="public_demo",
        max_reply_chars=cfg.session_max_reply_chars,
        chars_per_credit=cfg.measured_chars_per_credit,
        max_turns=cfg.session_max_turns,
    )
    session_api.bind(state)
    log.info("Ready. mock_apis=%s embedder=%s", cfg.mock_apis, state.semantic_cache.embedder_name)
    yield


app = FastAPI(title="Gnani Voice Gateway API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(session_api.router)  # GET /session and WS /ws/session

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
async def root():
    """The session demo is the only view, so the root sends you straight to it."""
    return RedirectResponse(url="/session")


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "mock_apis": state.config.mock_apis,
        "kill_switch": state.config.kill_switch,
        "embedder": state.semantic_cache.embedder_name,
    }


@app.get("/api/budget")
async def get_budget():
    """JSON only (no UI). Handy for checking bucket spend without a dashboard."""
    return state.budget_tracker.get_status()


@app.get("/api/intents")
async def get_intents():
    """Returns the supported non-personal and personal intent catalog."""
    return [
        {
            "id": intent.id,
            "personal": intent.personal,
            "languages": list(intent.languages.keys()),
            "canonical_reply": {k: v.canonical_reply for k, v in intent.languages.items()},
            "examples": {k: v.examples for k, v in intent.languages.items()},
        }
        for intent in state.intent_catalog.intents.values()
    ]