# Session demo: install and run

Copy this folder's contents over your repo root (paths mirror the repo), then:

    python apply_integration.py          # patches main.py, config.py, static/index.html (safe to re-run)
    cd backend
    python -m pytest tests -q            # existing tests + 17 new ones, all offline
    MOCK_APIS=1 uvicorn app.main:app --reload     # PowerShell: $env:MOCK_APIS="1"; uvicorn app.main:app --reload
    open http://localhost:8000/session

## New files
| File | Purpose |
|---|---|
| backend/app/metrics/timeline.py | One clock, shared t0, spans, `unattributed_ms` |
| backend/app/pipeline/session.py | One LLM layer, two TTS arms on the same text, session-scoped cache |
| backend/app/session_api.py | `/session` page and `/ws/session` websocket, per-session and per-IP caps |
| backend/app/static/session.html, session.js | Two-arm UI, per-turn rows, running savings |
| backend/tests/test_session.py, test_session_api.py | Offline tests |
| apply_integration.py | Wires the above into main.py / config.py / index.html |

## Metric definitions (identical for both arms)
- t0: the moment the reply text is final (after LLM or LLM cache)
- first_byte: t0 to first audio byte handed to the sender (server side)
- first_playable ("first sound"): t0 to the end of clause 1, a complete playable clip
- total: t0 to the last byte of the last clause
- unattributed_ms: total minus the union of all spans; tests fail if it exceeds 50 ms

## Before going live
1. Run once with MOCK_APIS=0 and ONE short session; compare the numbers with the offline run.
2. Edit GUIDED in static/session.js to match data/intents.yaml.
3. Tune SESSION_SEMANTIC_THRESHOLD on real paraphrases (e5 scores are compressed).
