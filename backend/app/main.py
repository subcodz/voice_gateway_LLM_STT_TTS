"""FastAPI application entrypoint, WebSocket gateway handler, and guardrail enforcement.

Why this module exists:
Provides the HTTP and WebSocket interface connecting web clients to the baseline and
gateway pipelines. It implements strict public demo guardrails (per-request character limits,
session throttles, daily IP quotas, and emergency kill switch) so that visitors can
interact with the live demo safely without exceeding budget constraints.
"""

import asyncio
from collections import defaultdict
import datetime
import json
import os
import time
from typing import Dict, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.adapters.fake import FakeTtsAdapter, FakeSttAdapter, FakeLlmAdapter
from app.adapters.gnani_tts import GnaniTtsAdapter
from app.adapters.gnani_stt import GnaniSttAdapter
from app.adapters.llm import LlmAdapter
from app.budget import BudgetTracker, BudgetExceededError, KillSwitchActiveError
from app.cache.audio_store import AudioStore
from app.cache.semantic import SemanticCache
from app.cache.singleflight import SingleFlight
from app.config import GatewayConfig, get_config
from app.metrics.store import MetricsStore
from app.pipeline.baseline import BaselinePipeline
from app.pipeline.gateway import GatewayPipeline
from app.routing.intents import IntentCatalog
from app.routing.router import Router

app = FastAPI(title="Gnani Voice Gateway API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global State Container
class AppState:
    config: GatewayConfig
    budget_tracker: BudgetTracker
    metrics_store: MetricsStore
    audio_store: AudioStore
    semantic_cache: SemanticCache
    singleflight: SingleFlight
    intent_catalog: IntentCatalog
    router: Router
    stt_adapter: object
    llm_adapter: object
    tts_adapter: object
    baseline_pipeline: BaselinePipeline
    gateway_pipeline: GatewayPipeline

    # Guardrails tracking: ip -> {date: str, chars: int}
    ip_daily_spend: Dict[str, Dict] = defaultdict(lambda: {"date": "", "chars": 0})
    # session_id -> chars: int
    session_spend: Dict[str, int] = defaultdict(int)

state = AppState()


@app.on_event("startup")
async def startup_event():
    cfg = get_config()
    state.config = cfg
    state.budget_tracker = BudgetTracker(db_path=cfg.db_path)
    state.metrics_store = MetricsStore(db_path=cfg.db_path)
    state.audio_store = AudioStore(
        cache_dir=cfg.cache_dir,
        l1_max_bytes=cfg.l1_max_bytes,
        l2_max_bytes=cfg.cache_max_bytes
    )
    state.singleflight = SingleFlight()
    state.semantic_cache = SemanticCache(threshold=cfg.semantic_threshold)

    # Load intents and seed semantic cache
    state.intent_catalog = IntentCatalog(yaml_path="data/intents.yaml")
    state.intent_catalog.populate_semantic_cache(state.semantic_cache)
    state.router = Router(state.intent_catalog, state.semantic_cache)

    # Initialize Adapters:
    # Use fake adapters in mock_apis mode to prevent accidental live credit spend!
    if cfg.mock_apis or not cfg.gnani_api_key:
        state.tts_adapter = FakeTtsAdapter(delay_ms=25)
        state.stt_adapter = FakeSttAdapter(delay_ms=20)
        state.llm_adapter = FakeLlmAdapter(delay_ms=30)
    else:
        state.tts_adapter = GnaniTtsAdapter(
            api_key=cfg.gnani_api_key,
            base_url=cfg.gnani_base_url,
            budget_tracker=state.budget_tracker,
            default_bucket="public_demo",
            kill_switch=cfg.kill_switch
        )
        state.stt_adapter = GnaniSttAdapter(
            api_key=cfg.gnani_api_key,
            base_url=cfg.gnani_base_url,
            budget_tracker=state.budget_tracker,
            bucket="public_demo",
            kill_switch=cfg.kill_switch
        )
        state.llm_adapter = LlmAdapter(
            groq_api_key=cfg.groq_api_key,
            gemini_api_key=cfg.gemini_api_key,
            groq_fast_model=cfg.groq_fast_model,
            groq_heavy_model=cfg.groq_heavy_model,
            gemini_model=cfg.gemini_model
        )

    # Initialize Baseline and Gateway Pipelines
    state.baseline_pipeline = BaselinePipeline(
        stt_adapter=state.stt_adapter,
        llm_adapter=state.llm_adapter,
        tts_adapter=state.tts_adapter,
        metrics_store=state.metrics_store,
        voice_map=cfg.voice_map,
        model=cfg.gnani_tts_model,
        sample_rate=cfg.gnani_sample_rate
    )
    state.gateway_pipeline = GatewayPipeline(
        stt_adapter=state.stt_adapter,
        llm_adapter=state.llm_adapter,
        tts_adapter=state.tts_adapter,
        router=state.router,
        audio_store=state.audio_store,
        singleflight=state.singleflight,
        metrics_store=state.metrics_store,
        voice_map=cfg.voice_map,
        model=cfg.gnani_tts_model,
        sample_rate=cfg.gnani_sample_rate,
        version_tag=cfg.version_tag,
        finish_on_disconnect=cfg.finish_on_disconnect
    )


def check_guardrails(ip: str, session_id: str, request_chars: int):
    """Enforces per-request, per-session, and per-IP daily caps."""
    cfg = state.config
    if cfg.kill_switch:
        raise HTTPException(status_code=503, detail="Public demo live synthesis is temporarily suspended via kill switch.")

    if request_chars > cfg.max_chars_per_request:
        raise HTTPException(
            status_code=400,
            detail=f"Request exceeds {cfg.max_chars_per_request} character limit for public demo."
        )

    if state.session_spend[session_id] + request_chars > cfg.max_chars_per_session:
        raise HTTPException(
            status_code=429,
            detail=f"Session quota exceeded ({cfg.max_chars_per_session} chars). Cached answers remain available."
        )

    today = datetime.date.today().isoformat()
    ip_rec = state.ip_daily_spend[ip]
    if ip_rec["date"] != today:
        ip_rec["date"] = today
        ip_rec["chars"] = 0

    if ip_rec["chars"] + request_chars > cfg.max_chars_per_ip_day:
        raise HTTPException(
            status_code=429,
            detail=f"Daily IP quota exceeded ({cfg.max_chars_per_ip_day} chars). Cached answers remain available."
        )


# Mount frontend static assets
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def serve_index():
    index_file = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Gnani Voice Gateway API Running"}


@app.get("/dashboard")
async def serve_dashboard():
    index_file = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Gnani Voice Gateway API Running"}


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "mock_apis": state.config.mock_apis,
        "kill_switch": state.config.kill_switch
    }


@app.get("/api/stats")
async def get_stats(run_id: Optional[str] = None):
    """Returns baseline vs gateway comparison metrics and cost avoidance."""
    return state.metrics_store.get_summary_stats(run_id=run_id)


@app.get("/api/turns")
async def get_recent_turns(limit: int = 50):
    """Returns recent turn timing waterfalls."""
    return state.metrics_store.get_recent_turns(limit=limit)


@app.get("/api/budget")
async def get_budget():
    """Returns current spend and caps across all budget buckets."""
    return state.budget_tracker.get_status()


@app.get("/api/intents")
async def get_intents():
    """Returns supported non-personal and personal intent catalog."""
    return [
        {
            "id": intent.id,
            "personal": intent.personal,
            "languages": list(intent.languages.keys()),
            "canonical_reply": {k: v.canonical_reply for k, v in intent.languages.items()},
            "examples": {k: v.examples for k, v in intent.languages.items()}
        }
        for intent in state.intent_catalog.intents.values()
    ]


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time WebSocket endpoint for conversational audio turns."""
    await websocket.accept()
    client_ip = websocket.client.host if websocket.client else "127.0.0.1"

    try:
        while True:
            # Receive either JSON metadata or binary audio
            message = await websocket.receive()
            if "text" in message and message["text"]:
                payload = json.loads(message["text"])
                arm = payload.get("arm", "gateway")
                session_id = payload.get("session_id", "default_sess")
                lang = payload.get("lang", "bn-IN")
                text = payload.get("text", "")
                run_id = payload.get("run_id", "demo")

                # Track guardrails for live typed text
                if text:
                    check_guardrails(client_ip, session_id, len(text))
                    state.session_spend[session_id] += len(text)
                    state.ip_daily_spend[client_ip]["chars"] += len(text)

                pipeline = state.gateway_pipeline if arm == "gateway" else state.baseline_pipeline

                async for item in pipeline.execute_turn(
                    session_id=session_id,
                    lang=lang,
                    text_input=text,
                    run_id=run_id
                ):
                    if isinstance(item, bytes):
                        await websocket.send_bytes(item)
                    elif isinstance(item, dict):
                        await websocket.send_json(item)

            elif "bytes" in message and message["bytes"]:
                # Push-to-talk 16kHz mono PCM WAV frame
                wav_bytes = message["bytes"]
                arm = "gateway"
                session_id = f"sess_{client_ip}"
                lang = "bn-IN"

                pipeline = state.gateway_pipeline if arm == "gateway" else state.baseline_pipeline

                async for item in pipeline.execute_turn(
                    session_id=session_id,
                    lang=lang,
                    wav_input=wav_bytes,
                    run_id="ptt_demo"
                ):
                    if isinstance(item, bytes):
                        await websocket.send_bytes(item)
                    elif isinstance(item, dict):
                        await websocket.send_json(item)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
