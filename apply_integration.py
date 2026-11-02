#!/usr/bin/env python3
"""Wires the session demo into main.py, config.py and index.html. Safe to re-run.

Usage (from the repo root):  python apply_integration.py
Each edit looks for an exact anchor line; if an anchor is missing the script stops
before writing anything to that file and tells you what to add by hand.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "backend/app/config.py"
MAIN = ROOT / "backend/app/main.py"
INDEX = ROOT / "backend/app/static/index.html"

CONFIG_ANCHOR = '    semantic_threshold: float = Field(default_factory=lambda: float(os.getenv("SEMANTIC_THRESHOLD", "0.82")))\n'
CONFIG_ADD = '''
    # Session demo (both TTS arms spend credits, so these caps matter)
    session_max_turns: int = 10
    session_max_tts_chars: int = 1500          # per session, both arms combined
    session_ip_tts_chars_day: int = 6000       # per IP per day, both arms combined
    session_max_reply_chars: int = 220         # reply is clipped to this before TTS
    session_ttl_s: int = 1800
    session_semantic_threshold: float = Field(default_factory=lambda: float(os.getenv("SESSION_SEMANTIC_THRESHOLD", "0.90")))
    measured_chars_per_credit: int = 370       # measured ratio, used for savings display (budget keeps 300)
'''

MAIN_IMPORT_ANCHOR = "from app.routing.router import Router\n"
MAIN_IMPORT_ADD = ("from app import session_api\n"
                   "from app.pipeline.session import SessionPipeline, SessionResponseCache, SessionStore\n")
MAIN_STATE_ANCHOR = "state = AppState()\n"
MAIN_STATE_ADD = "app.include_router(session_api.router)\n"
MAIN_STARTUP_ANCHOR = "        finish_on_disconnect=cfg.finish_on_disconnect\n    )\n"
MAIN_STARTUP_ADD = '''
    # Session demo: one LLM layer, two TTS paths, per-session cache namespace
    state.session_store = SessionStore(
        make_cache=lambda: SessionResponseCache(state.semantic_cache, threshold=cfg.session_semantic_threshold),
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
'''

INDEX_ANCHOR = """<button id="tab-budget-btn" class="nav-tab" onclick="switchTab('budget')">Budget Tracker</button>\n"""
INDEX_ADD = """        <button class="nav-tab" onclick="location.href='/session'">Session Demo</button>\n"""


def patch(path, edits, marker):
    text = path.read_text(encoding="utf-8")
    if marker in text:
        print(f"[skip] {path.relative_to(ROOT)} already patched")
        return True
    for anchor, add, where in edits:
        if text.count(anchor) != 1:
            print(f"[FAIL] {path.relative_to(ROOT)}: anchor not found exactly once:\n    {anchor.strip()}\n"
                  f"       Nothing was written to this file. Add the block by hand.")
            return False
    for anchor, add, where in edits:
        text = text.replace(anchor, anchor + add if where == "after" else add + anchor)
    path.write_text(text, encoding="utf-8")
    print(f"[ok]   {path.relative_to(ROOT)}")
    return True


ok = True
ok &= patch(CONFIG, [(CONFIG_ANCHOR, CONFIG_ADD, "after")], "session_max_tts_chars")
ok &= patch(MAIN, [(MAIN_IMPORT_ANCHOR, MAIN_IMPORT_ADD, "after"),
                   (MAIN_STATE_ANCHOR, MAIN_STATE_ADD, "after"),
                   (MAIN_STARTUP_ANCHOR, MAIN_STARTUP_ADD, "after")], "session_api.bind(state)")
ok &= patch(INDEX, [(INDEX_ANCHOR, INDEX_ADD, "after")], "location.href='/session'")
sys.exit(0 if ok else 1)
