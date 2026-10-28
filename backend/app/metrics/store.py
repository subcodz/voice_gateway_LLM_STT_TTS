"""SQLite storage for conversational turn metrics and cache telemetry.

Why this module exists:
Persists timing waterfalls (STT, Router, LLM, TTFA, and Total latency), cache hit rates,
and API calls/characters avoided for every turn. Provides aggregation queries that feed
the real-time web dashboard and automated benchmarking suite.
"""

import sqlite3
import threading
import time
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class TurnMetric(BaseModel):
    id: Optional[str] = None
    run_id: str = "default"
    arm: str = "gateway"  # 'baseline' or 'gateway'
    session_id: str = ""
    ts: float = Field(default_factory=time.time)
    lang: str = "bn-IN"
    route: str = "fast_llm"
    intent_id: Optional[str] = None
    sim_score: float = 0.0
    stt_ms: int = 0
    route_ms: int = 0
    llm_ms: int = 0
    ttfa_ms: int = 0
    total_ms: int = 0
    clauses: int = 0
    clause_hits: int = 0
    tts_calls: int = 0
    tts_chars: int = 0
    llm_calls: int = 0
    retries: int = 0


class MetricsStore:
    def __init__(self, db_path: str = "metrics.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_tables()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        with self._lock:
            with self._get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS turns (
                        id TEXT PRIMARY KEY,
                        run_id TEXT,
                        arm TEXT,
                        session_id TEXT,
                        ts REAL,
                        lang TEXT,
                        route TEXT,
                        intent_id TEXT,
                        sim_score REAL,
                        stt_ms INTEGER,
                        route_ms INTEGER,
                        llm_ms INTEGER,
                        ttfa_ms INTEGER,
                        total_ms INTEGER,
                        clauses INTEGER,
                        clause_hits INTEGER,
                        tts_calls INTEGER,
                        tts_chars INTEGER,
                        llm_calls INTEGER,
                        retries INTEGER
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS cache_entries (
                        key TEXT PRIMARY KEY,
                        bytes INTEGER,
                        created_at REAL,
                        last_used_at REAL,
                        hits INTEGER DEFAULT 0,
                        voice TEXT,
                        model TEXT,
                        lang TEXT,
                        text_len INTEGER
                    )
                """)
                conn.commit()

    def log_turn(self, turn: TurnMetric):
        """Records a completed turn's waterfall metrics."""
        import uuid
        turn_id = turn.id or str(uuid.uuid4())
        with self._lock:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO turns (
                        id, run_id, arm, session_id, ts, lang, route, intent_id, sim_score,
                        stt_ms, route_ms, llm_ms, ttfa_ms, total_ms,
                        clauses, clause_hits, tts_calls, tts_chars, llm_calls, retries
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    turn_id, turn.run_id, turn.arm, turn.session_id, turn.ts, turn.lang,
                    turn.route, turn.intent_id, turn.sim_score,
                    turn.stt_ms, turn.route_ms, turn.llm_ms, turn.ttfa_ms, turn.total_ms,
                    turn.clauses, turn.clause_hits, turn.tts_calls, turn.tts_chars,
                    turn.llm_calls, turn.retries
                ))
                conn.commit()

    def record_cache_hit(self, key: str):
        """Increments hit count and updates last_used_at for a cache entry."""
        with self._lock:
            with self._get_connection() as conn:
                conn.execute("""
                    UPDATE cache_entries
                    SET hits = hits + 1, last_used_at = ?
                    WHERE key = ?
                """, (time.time(), key))
                conn.commit()

    def record_cache_entry(self, key: str, size_bytes: int, voice: str, model: str, lang: str, text_len: int):
        """Registers a newly committed cache item in the metadata table."""
        now = time.time()
        with self._lock:
            with self._get_connection() as conn:
                conn.execute("""
                    INSERT INTO cache_entries (key, bytes, created_at, last_used_at, hits, voice, model, lang, text_len)
                    VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET last_used_at = ?
                """, (key, size_bytes, now, now, voice, model, lang, text_len, now))
                conn.commit()

    def get_summary_stats(self, run_id: Optional[str] = None) -> Dict:
        """Computes aggregate comparison statistics between baseline and gateway."""
        with self._lock:
            with self._get_connection() as conn:
                query = "SELECT * FROM turns"
                params = []
                if run_id:
                    query += " WHERE run_id = ?"
                    params.append(run_id)

                cur = conn.execute(query, params)
                rows = cur.fetchall()

        stats = {
            "baseline": {"count": 0, "ttfa_list": [], "total_ms_list": [], "tts_calls": 0, "tts_chars": 0, "llm_calls": 0},
            "gateway": {"count": 0, "ttfa_list": [], "total_ms_list": [], "tts_calls": 0, "tts_chars": 0, "llm_calls": 0, "clause_hits": 0, "total_clauses": 0}
        }

        for r in rows:
            arm = r["arm"]
            if arm in stats:
                stats[arm]["count"] += 1
                stats[arm]["ttfa_list"].append(r["ttfa_ms"])
                stats[arm]["total_ms_list"].append(r["total_ms"])
                stats[arm]["tts_calls"] += r["tts_calls"]
                stats[arm]["tts_chars"] += r["tts_chars"]
                stats[arm]["llm_calls"] += r["llm_calls"]
                if arm == "gateway":
                    stats["gateway"]["clause_hits"] += r["clause_hits"]
                    stats["gateway"]["total_clauses"] += r["clauses"]

        def _calc_p(lst, p):
            if not lst:
                return 0
            sorted_lst = sorted(lst)
            k = (len(sorted_lst) - 1) * (p / 100.0)
            f = int(k)
            c = min(f + 1, len(sorted_lst) - 1)
            return int(sorted_lst[f] + (k - f) * (sorted_lst[c] - sorted_lst[f]))

        gw_clauses = stats["gateway"]["total_clauses"]
        gw_hits = stats["gateway"]["clause_hits"]
        audio_hit_rate = round((gw_hits / gw_clauses * 100), 1) if gw_clauses > 0 else 0.0

        return {
            "baseline": {
                "turns": stats["baseline"]["count"],
                "ttfa_p50_ms": _calc_p(stats["baseline"]["ttfa_list"], 50),
                "ttfa_p95_ms": _calc_p(stats["baseline"]["ttfa_list"], 95),
                "total_p50_ms": _calc_p(stats["baseline"]["total_ms_list"], 50),
                "tts_calls": stats["baseline"]["tts_calls"],
                "tts_chars": stats["baseline"]["tts_chars"],
                "llm_calls": stats["baseline"]["llm_calls"],
            },
            "gateway": {
                "turns": stats["gateway"]["count"],
                "ttfa_p50_ms": _calc_p(stats["gateway"]["ttfa_list"], 50),
                "ttfa_p95_ms": _calc_p(stats["gateway"]["ttfa_list"], 95),
                "total_p50_ms": _calc_p(stats["gateway"]["total_ms_list"], 50),
                "tts_calls": stats["gateway"]["tts_calls"],
                "tts_chars": stats["gateway"]["tts_chars"],
                "llm_calls": stats["gateway"]["llm_calls"],
                "audio_hit_rate_pct": audio_hit_rate,
            },
            "savings": {
                "tts_calls_avoided": max(0, stats["baseline"]["tts_calls"] - stats["gateway"]["tts_calls"]),
                "tts_chars_avoided": max(0, stats["baseline"]["tts_chars"] - stats["gateway"]["tts_chars"]),
                "llm_calls_avoided": max(0, stats["baseline"]["llm_calls"] - stats["gateway"]["llm_calls"]),
            }
        }

    def get_recent_turns(self, limit: int = 50) -> List[Dict]:
        """Returns the most recent turns for the waterfall dashboard."""
        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute("""
                    SELECT * FROM turns ORDER BY ts DESC LIMIT ?
                """, (limit,))
                return [dict(r) for r in cur.fetchall()]
