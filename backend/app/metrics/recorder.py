"""Turn timing recorder and telemetry aggregator.

Why this module exists:
Instruments each conversational turn with microsecond-resolution stage timers
(STT, Router, LLM, TTFA, and Total). Accumulates clause-level cache hits, characters
synthesized, and retry counts, guaranteeing accurate performance and cost avoidance tracking.
"""

import time
import uuid
from typing import Optional
from app.metrics.store import MetricsStore, TurnMetric


class TurnRecorder:
    def __init__(
        self,
        store: MetricsStore,
        arm: str = "gateway",
        session_id: str = "",
        lang: str = "bn-IN",
        run_id: str = "default"
    ):
        self.store = store
        self.turn_id = str(uuid.uuid4())
        self.arm = arm
        self.session_id = session_id
        self.lang = lang
        self.run_id = run_id

        self.t0 = time.perf_counter()
        self.stt_ms = 0
        self.route_ms = 0
        self.llm_ms = 0
        self.ttfa_ms = 0
        self.total_ms = 0

        self.route_decision = "fast_llm"
        self.intent_id: Optional[str] = None
        self.sim_score = 0.0

        self.clauses_count = 0
        self.clause_hits = 0
        self.tts_calls = 0
        self.tts_chars = 0
        self.llm_calls = 0
        self.retries = 0

        self._first_audio_recorded = False

    def record_stt(self, duration_ms: int):
        self.stt_ms = duration_ms

    def record_route(self, duration_ms: int, decision: str, intent_id: Optional[str] = None, sim_score: float = 0.0):
        self.route_ms = duration_ms
        self.route_decision = decision
        self.intent_id = intent_id
        self.sim_score = sim_score

    def record_llm(self, duration_ms: int, calls: int = 1):
        self.llm_ms = duration_ms
        self.llm_calls += calls

    def record_ttfa(self):
        """Records time to first audio chunk from the turn start."""
        if not self._first_audio_recorded:
            self.ttfa_ms = round((time.perf_counter() - self.t0) * 1000)
            self._first_audio_recorded = True

    def record_clause(self, hit: bool, chars: int, is_tts_call: bool = False):
        self.clauses_count += 1
        if hit:
            self.clause_hits += 1
        if is_tts_call:
            self.tts_calls += 1
            self.tts_chars += chars

    def record_retry(self):
        self.retries += 1

    def finish(self) -> TurnMetric:
        """Finishes the turn, calculates total duration, and commits to MetricsStore."""
        self.total_ms = round((time.perf_counter() - self.t0) * 1000)
        if not self._first_audio_recorded:
            self.ttfa_ms = self.total_ms

        metric = TurnMetric(
            id=self.turn_id,
            run_id=self.run_id,
            arm=self.arm,
            session_id=self.session_id,
            lang=self.lang,
            route=self.route_decision,
            intent_id=self.intent_id,
            sim_score=self.sim_score,
            stt_ms=self.stt_ms,
            route_ms=self.route_ms,
            llm_ms=self.llm_ms,
            ttfa_ms=self.ttfa_ms,
            total_ms=self.total_ms,
            clauses=self.clauses_count,
            clause_hits=self.clause_hits,
            tts_calls=self.tts_calls,
            tts_chars=self.tts_chars,
            llm_calls=self.llm_calls,
            retries=self.retries
        )
        self.store.log_turn(metric)
        return metric
