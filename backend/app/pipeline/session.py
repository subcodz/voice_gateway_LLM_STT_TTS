"""Session demo pipeline: one LLM layer, two TTS paths, identical reply text.

Why this module exists:
The split-screen demo ran two independent pipelines, so each arm got a different
LLM answer and the comparison was contaminated. Here a turn works like this:

  route -> LLM layer (intent cache / session response cache / LLM), ONCE
        -> the same reply text is split into the same clauses
        -> arm "cached":   per-clause audio cache lookup, tee-commit on a miss
        -> arm "uncached": every clause goes to TTS, nothing is read or written

Both arms use the same TTS adapter, the same clause splitting, the same streaming
code path and the same t0, so the only variable is the audio cache.

The audio cache is namespaced by session id (through the key's version tag), so every
demo session starts cold regardless of what other visitors or rehearsals cached.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple, Union

from app.adapters.models import Msg, TtsRequest, TtsStats
from app.cache.audio_store import AudioStore
from app.cache.keys import audio_key, normalize_speech_text
from app.cache.semantic import SemanticCache, cosine_similarity
from app.cache.tee import tee_stream
from app.metrics.timeline import Timeline
from app.routing.splitter import split_into_clauses

log = logging.getLogger("session")

ARMS = ("cached", "uncached")
_ARM_FINISHED = object()

FALLBACK_REPLY = "Thank you, I am processing your request."


# ---------------------------------------------------------------- helpers


def clip_reply(text: str, max_chars: int) -> str:
    """Keeps a demo reply under max_chars, cutting at a sentence boundary when possible.

    The LLM prompt asks for two short sentences but models drift; this bounds the
    characters each arm can spend per turn."""
    text = text.strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    kept = ""
    for clause in split_into_clauses(text):
        candidate = f"{kept} {clause}".strip()
        if len(candidate) > max_chars:
            break
        kept = candidate
    if kept:
        return kept
    cut = text[:max_chars]
    space = cut.rfind(" ")
    return (cut[:space] if space > 0 else cut).rstrip(" ,;:") + "."


def _norm_query(text: str) -> str:
    return normalize_speech_text(text).lower().strip(" ?!.,;:।॥")


# ---------------------------------------------------------------- LLM-layer cache


@dataclass
class _Entry:
    query: str
    lang: str
    vec: List[float]
    reply: str


class SessionResponseCache:
    """Per-session cache of LLM replies: exact (normalized) match first, then semantic.

    Never used for personalized queries. Embeddings come from the shared SemanticCache
    embedder. Note: multilingual-e5 scores are compressed (unrelated sentences often
    score 0.7-0.8), so keep the threshold high and tune it on real paraphrases."""

    def __init__(self, semantic: SemanticCache, threshold: float = 0.90):
        self.semantic = semantic
        self.threshold = threshold
        self._exact: Dict[Tuple[str, str], str] = {}
        self._entries: List[_Entry] = []

    def lookup(self, text: str, lang: str) -> Optional[Tuple[str, str, float]]:
        """Returns (reply, 'exact_hit' | 'semantic_hit', score) or None."""
        exact = self._exact.get((lang, _norm_query(text)))
        if exact is not None:
            return exact, "exact_hit", 1.0
        if not self._entries:
            return None
        vec = self.semantic.embed_text(text, is_query=True)
        best: Optional[_Entry] = None
        best_score = -1.0
        for e in self._entries:
            if e.lang != lang:
                continue
            score = cosine_similarity(vec, e.vec)
            if score > best_score:
                best, best_score = e, score
        if best is not None and best_score >= self.threshold:
            return best.reply, "semantic_hit", round(best_score, 4)
        return None

    def store(self, text: str, lang: str, reply: str) -> None:
        key = (lang, _norm_query(text))
        if key in self._exact:
            return
        self._exact[key] = reply
        self._entries.append(_Entry(text, lang, self.semantic.embed_text(text, is_query=True), reply))


# ---------------------------------------------------------------- session state


def _empty_arm_totals() -> Dict[str, float]:
    return {
        "turns": 0, "tts_calls": 0, "tts_chars": 0,
        "clauses": 0, "clause_hits": 0,
        "first_playable_ms": 0.0, "total_ms": 0.0, "timed_turns": 0,
    }


class DemoSession:
    def __init__(self, session_id: str, response_cache: SessionResponseCache):
        self.session_id = session_id
        self.cache = response_cache
        self.created = time.time()
        self.last_used = self.created
        self.turns = 0
        self.tts_chars_spent = 0  # real characters sent to TTS, both arms combined
        self.arms: Dict[str, Dict[str, float]] = {a: _empty_arm_totals() for a in ARMS}
        self.llm = {"calls": 0, "exact_hits": 0, "semantic_hits": 0, "intent_hits": 0}
        self.saved = {"tts_chars": 0, "tts_calls": 0, "first_playable_ms": 0.0,
                      "total_ms": 0.0, "compared_turns": 0, "noisy_turns": 0}

    def touch(self) -> None:
        self.last_used = time.time()


class SessionStore:
    def __init__(self, make_cache: Callable[[], SessionResponseCache], ttl_s: int = 1800, max_sessions: int = 200):
        self._make_cache = make_cache
        self._ttl_s = ttl_s
        self._max = max_sessions
        self._sessions: Dict[str, DemoSession] = {}

    def get_or_create(self, session_id: str) -> DemoSession:
        self._prune()
        s = self._sessions.get(session_id)
        if s is None:
            s = DemoSession(session_id, self._make_cache())
            self._sessions[session_id] = s
        s.touch()
        return s

    def drop(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def _prune(self) -> None:
        now = time.time()
        for sid in [k for k, v in self._sessions.items() if now - v.last_used > self._ttl_s]:
            del self._sessions[sid]
        while len(self._sessions) >= self._max:
            oldest = min(self._sessions.items(), key=lambda kv: kv[1].last_used)[0]
            del self._sessions[oldest]


# ---------------------------------------------------------------- pipeline


class SessionPipeline:
    def __init__(
        self,
        llm_adapter,
        tts_adapter,
        audio_store: AudioStore,
        router,
        voice_map: Dict[str, str],
        model: str = "timbre-v2.5",
        sample_rate: int = 48000,
        version_tag: str = "v1",
        bucket: str = "public_demo",
        max_reply_chars: int = 220,
        chars_per_credit: float = 370.0,
        max_turns: int = 10,
    ):
        self.llm = llm_adapter
        self.tts = tts_adapter
        self.audio_store = audio_store
        self.router = router
        self.voice_map = voice_map
        self.model = model
        self.sample_rate = sample_rate
        self.version_tag = version_tag
        self.bucket = bucket
        self.max_reply_chars = max_reply_chars
        # Measured billing ratio (~370 chars/credit). The BudgetTracker uses 300 so it
        # over-counts spend, which is right for a cap but would overstate savings here.
        self.chars_per_credit = chars_per_credit
        self.max_turns = max_turns

    # ------------------------------------------------------------ public

    async def execute_turn(
        self,
        session: DemoSession,
        text: str,
        lang: str,
        budget_chars: Optional[int] = None,
    ) -> AsyncIterator[Union[dict, bytes]]:
        """Runs one conversational turn.

        Yields dict events and bytes. Every bytes item is the payload of the 'audio'
        dict event immediately before it. budget_chars bounds the worst-case TTS spend
        (both arms) for this turn; None means unbounded."""
        text = (text or "").strip()
        if not text:
            yield {"type": "error", "message": "Empty message."}
            return
        if session.turns >= self.max_turns:
            yield {"type": "cap", "reason": "turns", "message": f"Demo sessions are limited to {self.max_turns} turns. Start a new session."}
            return

        session.touch()
        session.turns += 1
        turn_no = session.turns
        tl = Timeline()
        yield {"type": "turn_start", "turn": turn_no, "text": text, "lang": lang}

        # ---- route
        decision, intent_id, canonical, sim = "fast_llm", None, None, 0.0
        if self.router is not None:
            sp = tl.begin("route")
            try:
                rd = self.router.route(text, lang=lang)
                decision, intent_id, canonical, sim = rd.decision, rd.intent_id, rd.canonical_reply, rd.sim_score
            except Exception:
                log.exception("Router failed; defaulting to fast_llm")
            tl.end(sp)

        # ---- LLM layer: intent cache -> session response cache -> LLM
        reply, source = "", "llm"
        if decision == "cached_intent" and canonical:
            reply, source = canonical, "intent_cache"
            session.llm["intent_hits"] += 1
        else:
            cacheable = decision != "personalized"
            if cacheable:
                sp = tl.begin("llm_cache_lookup")
                hit = await asyncio.to_thread(session.cache.lookup, text, lang)
                tl.end(sp)
                if hit:
                    reply, source, sim = hit
                    session.llm["exact_hits" if source == "exact_hit" else "semantic_hits"] += 1
            if not reply:
                sp = tl.begin("llm")
                tier = "heavy" if decision == "heavy_llm" else "fast"
                llm_ok = True
                history = [Msg(role="user", content=text)]
                try:
                    reply = await self.llm.reply(history, tier=tier)
                except Exception:
                    log.exception("LLM %s tier failed", tier)
                    try:
                        reply = await self.llm.reply(history, tier="heavy")
                    except Exception:
                        log.exception("LLM heavy tier failed")
                        reply, llm_ok = FALLBACK_REPLY, False
                tl.end(sp)
                session.llm["calls"] += 1
                reply = clip_reply(reply or "", self.max_reply_chars)
                if reply and cacheable and llm_ok:
                    await asyncio.to_thread(session.cache.store, text, lang, reply)
                source = "llm" if cacheable else "llm_uncacheable"
                if not llm_ok:
                    source = "llm_failed"

        reply_ready_ms = tl.finish()
        if not reply.strip():
            yield {"type": "error", "message": "The LLM returned an empty reply."}
            return

        yield {
            "type": "reply", "turn": turn_no, "text": reply, "source": source,
            "route": decision, "intent_id": intent_id, "sim_score": sim,
            "reply_ready_ms": round(reply_ready_ms, 1),
            "spans": {k: round(v, 1) for k, v in tl.by_name().items()},
        }

        # ---- identical clauses for both arms
        clauses = split_into_clauses(reply) or [reply]
        chars = sum(len(c) for c in clauses)
        worst_case = 2 * chars  # both arms synthesize everything on a cold turn
        if budget_chars is not None and worst_case > budget_chars:
            yield {"type": "cap", "reason": "chars", "needed": worst_case, "remaining": max(0, budget_chars),
                   "message": "Demo character limit reached, so audio was skipped for this turn."}
            return

        voice = self.voice_map.get(lang) or ("Kirra" if "bn" in lang else "Nalini" if "hi" in lang else "Poorvi")

        # ---- run both arms against the SAME t0
        out: asyncio.Queue = asyncio.Queue()
        # Alternate who goes first so connection-warmth bias cancels out over a session.
        order = ARMS if turn_no % 2 == 1 else tuple(reversed(ARMS))

        async def run_both() -> None:
            for arm in order:
                # Fresh t0 per arm: each arm is timed from its own start.
                await self._run_arm(arm, arm == "cached", session, clauses, voice, lang,
                                    time.perf_counter(), out)

        tasks = [asyncio.create_task(run_both())]
        results: Dict[str, dict] = {}
        pending = len(ARMS)   # one _ARM_FINISHED per arm
        try:
            while pending:
                item = await out.get()
                if item is _ARM_FINISHED:
                    pending -= 1
                    continue
                if isinstance(item, dict) and item.get("type") == "arm_done":
                    results[item["arm"]] = item["metrics"]
                yield item
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        summary = self._finalize_turn(session, results)
        yield {"type": "turn_done", "turn": turn_no, "turn_summary": summary, "session": self.snapshot(session)}

    def snapshot(self, session: DemoSession) -> dict:
        arms = {}
        for a in ARMS:
            t = dict(session.arms[a])
            t["est_credits"] = round(t["tts_chars"] / self.chars_per_credit, 3)
            arms[a] = t
        saved = dict(session.saved)
        saved["est_credits"] = round(saved["tts_chars"] / self.chars_per_credit, 3)
        return {
            "session_id": session.session_id, "turns": session.turns,
            "tts_chars_spent": session.tts_chars_spent,
            "chars_per_credit": self.chars_per_credit,
            "arms": arms, "llm": dict(session.llm), "saved": saved,
        }

    # ------------------------------------------------------------ internals

    @staticmethod
    def _emit_audio(out: asyncio.Queue, arm: str, clause: int, data: bytes) -> None:
        # Two consecutive put_nowait calls with no await between them cannot be
        # interleaved with the other arm, so the header always precedes its payload.
        out.put_nowait({"type": "audio", "arm": arm, "clause": clause, "size": len(data)})
        out.put_nowait(bytes(data))

    async def _run_arm(self, arm, use_cache, session, clauses, voice, lang, t0, out) -> None:
        tl = Timeline(t0=t0)
        calls = chars = hits = retries = 0
        error: Optional[str] = None
        namespace = f"{self.version_tag}:{session.session_id}"
        try:
            for idx, clause in enumerate(clauses):
                clause_start = tl.now_ms()
                req = TtsRequest(text=clause, voice=voice, model=self.model,
                                 language=lang, sample_rate=self.sample_rate)
                key = audio_key(req, version_tag=namespace) if use_cache else None
                cached: Optional[bytes] = None
                if use_cache:
                    sp = tl.begin("cache_lookup")
                    cached = self.audio_store.get(key)
                    tl.end(sp)

                if cached:
                    source = "hit"
                    tl.mark("first_byte")
                    self._emit_audio(out, arm, idx, cached)
                    hits += 1
                else:
                    source = "miss" if use_cache else "live"
                    stats = TtsStats()
                    stream = self.tts.stream(req, stats=stats, bucket=self.bucket)
                    if use_cache:
                        stream = tee_stream(stream, self.audio_store, key, finish_on_disconnect=False)
                    sp = tl.begin("tts_first_byte")
                    got_first = False
                    async for chunk in stream:
                        if not got_first:
                            got_first = True
                            tl.end(sp)
                            tl.mark("first_byte")
                            sp = tl.begin("tts_stream")
                        self._emit_audio(out, arm, idx, chunk)
                    tl.end(sp)
                    if not got_first:
                        raise RuntimeError("TTS returned no audio")
                    calls += 1
                    chars += len(clause)
                    retries += stats.retries

                if idx == 0:
                    tl.mark("first_playable")
                out.put_nowait({"type": "clause_done", "arm": arm, "clause": idx, "source": source,
                                "chars": len(clause), "clause_ms": round(tl.now_ms() - clause_start, 1)})
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one arm failing must not kill the other
            log.exception("%s arm failed", arm)
            error = str(exc) or exc.__class__.__name__

        total = tl.finish()

        def r(v: Optional[float]) -> Optional[float]:
            return None if v is None else round(v, 1)

        out.put_nowait({"type": "arm_done", "arm": arm, "metrics": {
            "arm": arm, "use_cache": use_cache,
            "first_byte_ms": r(tl.marks.get("first_byte")),
            "first_playable_ms": r(tl.marks.get("first_playable")),
            "total_ms": r(total),
            "clauses": len(clauses), "clause_hits": hits,
            "tts_calls": calls, "tts_chars": chars,
            "est_credits": round(chars / self.chars_per_credit, 3),
            "retries": retries, "noisy": retries > 0,
            "spans": {k: round(v, 1) for k, v in tl.by_name().items()},
            "unattributed_ms": round(tl.unattributed_ms(), 1),
            "error": error,
        }})
        out.put_nowait(_ARM_FINISHED)

    def _finalize_turn(self, session: DemoSession, results: Dict[str, dict]) -> dict:
        c, u = results.get("cached"), results.get("uncached")
        spent = sum(m["tts_chars"] for m in (c, u) if m)
        session.tts_chars_spent += spent
        summary: Dict[str, Any] = {"spent_chars": spent, "compared": False}
        if not c or not u or c["error"] or u["error"]:
            summary["errors"] = {a: (results.get(a) or {}).get("error") for a in ARMS}
            return summary

        noisy = bool(c["noisy"] or u["noisy"])
        # Time is only comparable when the cache actually served something and
        # retries did not distort the run. On a pure-miss turn both arms did the
        # same work, so any gap is jitter.
        timed = c["clause_hits"] > 0 and not noisy

        for arm, m in (("cached", c), ("uncached", u)):
            t = session.arms[arm]
            t["turns"] += 1
            t["tts_calls"] += m["tts_calls"]
            t["tts_chars"] += m["tts_chars"]
            t["clauses"] += m["clauses"]
            t["clause_hits"] += m["clause_hits"]
            if timed:
                t["first_playable_ms"] += m["first_playable_ms"] or 0.0
                t["total_ms"] += m["total_ms"] or 0.0
                t["timed_turns"] += 1

        s = session.saved
        s["tts_chars"] += u["tts_chars"] - c["tts_chars"]
        s["tts_calls"] += u["tts_calls"] - c["tts_calls"]
        if timed:
            s["first_playable_ms"] += max(0.0, (u["first_playable_ms"] or 0.0) - (c["first_playable_ms"] or 0.0))
            s["total_ms"] += max(0.0, u["total_ms"] - c["total_ms"])
        s["compared_turns"] += 1
        s["noisy_turns"] += 1 if noisy else 0
        summary.update({
            "compared": True, "noisy": noisy,
            "saved_chars": u["tts_chars"] - c["tts_chars"],
            "saved_calls": u["tts_calls"] - c["tts_calls"],
            "saved_first_playable_ms": round((u["first_playable_ms"] or 0.0) - (c["first_playable_ms"] or 0.0), 1),
            "saved_total_ms": round(u["total_ms"] - c["total_ms"], 1),
        })
        return summary
