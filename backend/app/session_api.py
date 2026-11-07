"""HTTP page + WebSocket endpoint for the session demo.

Why this module exists:
Keeps the session demo out of main.py. main.py only builds the pipeline on startup,
calls bind(state) and includes this router.

Protocol (client -> server, JSON text frames):
  {"type": "turn",  "session_id": "<uuid>", "text": "...", "lang": "hi-IN"|"bn-IN"|"hi-en" (optional)}
  {"type": "reset", "session_id": "<uuid>"}

Server -> client: JSON events from SessionPipeline.execute_turn. An {"type": "audio"}
event is always followed by exactly one binary frame holding that chunk's bytes.

Spend guardrails (this demo runs BOTH arms, so each turn can cost up to 2x the reply):
  - max input length per message        cfg.max_chars_per_request
  - TTS characters per session          cfg.session_max_tts_chars
  - TTS characters per IP per day       cfg.session_ip_tts_chars_day
  - the BudgetTracker 'public_demo' bucket remains the hard backstop
"""

import datetime
import json
import logging
import os
from collections import defaultdict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

router = APIRouter()
log = logging.getLogger("session_api")

_state = None
_ip_spend = defaultdict(lambda: {"date": "", "chars": 0})
_VALID_LANGS = {"hi-IN", "bn-IN", "hi-en"}
_STATIC = os.path.join(os.path.dirname(__file__), "static")
_FRONTEND_DIST = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist"))


def bind(state) -> None:
    """Called once from main.py's startup hook, after the pipeline is built."""
    global _state
    _state = state


@router.get("/session")
async def session_page():
    dist_index = os.path.join(_FRONTEND_DIST, "index.html")
    if os.path.exists(dist_index):
        return FileResponse(dist_index)
    return FileResponse(os.path.join(_STATIC, "session.html"))


def _ip_remaining(ip: str, cap: int) -> int:
    rec = _ip_spend[ip]
    today = datetime.date.today().isoformat()
    if rec["date"] != today:
        rec["date"], rec["chars"] = today, 0
    return cap - rec["chars"]


@router.websocket("/ws/session")
async def ws_session(ws: WebSocket):
    from app.routing.router import detect_language  # local import keeps this module light

    await ws.accept()
    st = _state
    cfg = st.config
    ip = ws.client.host if ws.client else "unknown"

    try:
        await ws.send_json({
            "type": "ready", "mock": cfg.mock_apis,
            "limits": {
                "max_turns": cfg.session_max_turns,
                "max_input_chars": cfg.max_chars_per_request,
                "session_tts_chars": cfg.session_max_tts_chars,
            },
        })
        while True:
            try:
                msg = json.loads(await ws.receive_text())
            except json.JSONDecodeError:
                await ws.send_json({"type": "error", "message": "Invalid message."})
                continue

            sid = str(msg.get("session_id") or "")[:64]
            if not sid:
                await ws.send_json({"type": "error", "message": "Missing session_id."})
                continue

            if msg.get("type") == "reset":
                st.session_store.drop(sid)
                await ws.send_json({"type": "reset_ok"})
                continue
            if msg.get("type") != "turn":
                continue

            text = str(msg.get("text") or "").strip()
            if len(text) > cfg.max_chars_per_request:
                await ws.send_json({"type": "error",
                                    "message": f"Messages are limited to {cfg.max_chars_per_request} characters in the demo."})
                continue

            lang = msg.get("lang")
            if lang not in _VALID_LANGS:
                lang = detect_language(text, fallback="hi-IN")

            session = st.session_store.get_or_create(sid)
            budget = min(
                cfg.session_max_tts_chars - session.tts_chars_spent,
                _ip_remaining(ip, cfg.session_ip_tts_chars_day),
            )

            async for item in st.session_pipeline.execute_turn(session, text, lang, budget_chars=budget):
                if isinstance(item, (bytes, bytearray)):
                    await ws.send_bytes(bytes(item))
                    continue
                await ws.send_json(item)
                if item.get("type") == "turn_done":
                    _ip_spend[ip]["chars"] += item["turn_summary"]["spent_chars"]

    except WebSocketDisconnect:
        log.info("session client disconnected: %s", ip)
    except Exception as exc:  # noqa: BLE001
        log.exception("session websocket error")
        try:
            await ws.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
