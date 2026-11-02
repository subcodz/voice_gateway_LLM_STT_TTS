"""WebSocket-level tests for the session demo endpoint."""

import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import session_api
from app.adapters.fake import FakeLlmAdapter, FakeTtsAdapter
from app.cache.audio_store import AudioStore
from app.cache.semantic import SemanticCache
from app.pipeline.session import SessionPipeline, SessionResponseCache, SessionStore

VOICES = {"hi-IN": "Nalini", "bn-IN": "Kirra", "hi-en": "Poorvi"}


def make_client(tmp_path, session_chars=1500):
    cfg = SimpleNamespace(
        mock_apis=True, max_chars_per_request=100, session_max_turns=10,
        session_max_tts_chars=session_chars, session_ip_tts_chars_day=100000,
    )
    sem = SemanticCache()
    store = SessionStore(lambda: SessionResponseCache(sem, 0.9))
    pipe = SessionPipeline(
        llm_adapter=FakeLlmAdapter(delay_ms=1), tts_adapter=FakeTtsAdapter(delay_ms=1),
        audio_store=AudioStore(cache_dir=str(tmp_path / "a")), router=None, voice_map=VOICES,
    )
    session_api.bind(SimpleNamespace(config=cfg, session_store=store, session_pipeline=pipe))
    session_api._ip_spend.clear()
    app = FastAPI()
    app.include_router(session_api.router)
    return TestClient(app)


def read_turn(ws):
    """Collects frames until turn_done/cap/error; returns (json_events, binary_frames)."""
    events, blobs = [], []
    while True:
        m = ws.receive()
        if m.get("bytes") is not None:
            blobs.append(m["bytes"])
            continue
        e = json.loads(m["text"])
        events.append(e)
        if e["type"] in ("turn_done", "cap", "error"):
            return events, blobs


def send(ws, **kw):
    ws.send_text(json.dumps(kw))


def test_turn_streams_paired_audio_frames_and_totals(tmp_path):
    with make_client(tmp_path).websocket_connect("/ws/session") as ws:
        assert ws.receive_json()["type"] == "ready"
        send(ws, type="turn", session_id="s1", text="how to apply for a new connection", lang="hi-en")
        events, blobs = read_turn(ws)
        headers = [e for e in events if e["type"] == "audio"]
        assert len(headers) == len(blobs) > 0                       # one binary frame per audio header
        assert [len(b) for b in blobs] and sum(h["size"] for h in headers) == sum(len(b) for b in blobs)
        done = events[-1]
        assert done["type"] == "turn_done" and done["session"]["turns"] == 1

        send(ws, type="turn", session_id="s1", text="how to apply for a new connection", lang="hi-en")
        events, _ = read_turn(ws)
        assert [e for e in events if e["type"] == "reply"][0]["source"] == "exact_hit"
        assert events[-1]["session"]["saved"]["tts_chars"] > 0


def test_input_length_cap_and_reset(tmp_path):
    with make_client(tmp_path).websocket_connect("/ws/session") as ws:
        ws.receive_json()
        send(ws, type="turn", session_id="s1", text="x" * 101)
        assert read_turn(ws)[0][-1]["type"] == "error"
        send(ws, type="turn", session_id="s1", text="hello there", lang="hi-en")
        read_turn(ws)
        send(ws, type="reset", session_id="s1")
        assert ws.receive_json()["type"] == "reset_ok"
        send(ws, type="turn", session_id="s1", text="hello there", lang="hi-en")
        events, _ = read_turn(ws)
        assert events[-1]["session"]["turns"] == 1                  # fresh session after reset


def test_session_char_cap_blocks_audio(tmp_path):
    with make_client(tmp_path, session_chars=20).websocket_connect("/ws/session") as ws:
        ws.receive_json()
        send(ws, type="turn", session_id="s1", text="hello there", lang="hi-en")
        events, blobs = read_turn(ws)
        assert events[-1]["type"] == "cap" and blobs == []
