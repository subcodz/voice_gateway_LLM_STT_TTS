"""Tests for the session demo: shared timeline, identical reply text, session-scoped cache."""

import asyncio
from types import SimpleNamespace

import pytest

from app.adapters.fake import FakeLlmAdapter, FakeTtsAdapter
from app.cache.audio_store import AudioStore
from app.cache.semantic import SemanticCache
from app.metrics.timeline import Timeline
from app.pipeline.session import (
    SessionPipeline, SessionResponseCache, SessionStore, clip_reply,
)

VOICES = {"hi-IN": "Nalini", "bn-IN": "Kirra", "hi-en": "Poorvi"}
Q = "What is the first step to apply for a new connection?"


class StubRouter:
    """Mock query router providing deterministic routing decisions for pipeline tests."""

    def __init__(self, decision="fast_llm", canonical=None):
        """Initialize the stub router with a target decision and optional canonical reply."""
        self.decision, self.canonical = decision, canonical

    def route(self, text, lang="bn-IN"):
        """Return a simulated routing decision matching the configured stub state."""
        return SimpleNamespace(decision=self.decision, intent_id=None,
                               canonical_reply=self.canonical, sim_score=0.0)


def build(tmp_path, router=None, threshold=0.90, max_turns=10, max_reply_chars=220):
    """Factory helper to wire up an isolated SessionPipeline test environment.
    
    Creates fake LLM and TTS adapters, an isolated temporary directory for audio cache,
    a fresh SemanticCache instance, and a SessionStore. Returns the pipeline, store, and adapters.
    """
    tts = FakeTtsAdapter(delay_ms=1)
    llm = FakeLlmAdapter(delay_ms=1)
    sem = SemanticCache()
    store = SessionStore(lambda: SessionResponseCache(sem, threshold=threshold))
    pipe = SessionPipeline(
        llm_adapter=llm, tts_adapter=tts,
        audio_store=AudioStore(cache_dir=str(tmp_path / "audio")),
        router=router or StubRouter(), voice_map=VOICES,
        max_turns=max_turns, max_reply_chars=max_reply_chars,
    )
    return pipe, store, tts, llm


async def run_turn(pipe, store, sid, text, lang="hi-en", budget=None):
    """Execute a single pipeline turn and unpack structured outputs for test assertions.
    
    Streams events and binary audio chunks from execute_turn, separating them into:
    - events: raw list of yielded event dictionaries
    - by: event dictionaries indexed by event type
    - arms: metric summaries indexed by arm name ('cached' vs 'uncached')
    - audio: byte buffers indexed by arm and clause index
    """
    events, audio = [], {"cached": {}, "uncached": {}}
    pending = None
    async for item in pipe.execute_turn(store.get_or_create(sid), text, lang, budget_chars=budget):
        if isinstance(item, (bytes, bytearray)):
            assert pending is not None, "audio payload arrived without its header"
            audio[pending["arm"]].setdefault(pending["clause"], bytearray()).extend(item)
            pending = None
        else:
            events.append(item)
            pending = item if item["type"] == "audio" else None
    by = {}
    for e in events:
        by.setdefault(e["type"], []).append(e)
    arms = {e["arm"]: e["metrics"] for e in by.get("arm_done", [])}
    return events, by, arms, audio


# ---------------------------------------------------------------- timeline


def test_timeline_union_does_not_double_count_overlap():
    """Verify Timeline span calculations compute the union of overlapping time intervals.
    
    Ensures that spans overlapping in time (e.g. [0,10] and [5,15]) do not double-count
    elapsed milliseconds when calculating covered and unattributed duration.
    """
    tl = Timeline(t0=0.0)
    tl.spans = []
    from app.metrics.timeline import Span
    tl.spans = [Span("a", 0, 10), Span("b", 5, 15), Span("c", 20, 25)]
    tl._end_ms = 30
    assert tl.covered_ms() == 20          # [0,15] + [20,25]
    assert tl.unattributed_ms() == 10


def test_timeline_first_mark_wins_and_finish_closes_open_spans():
    """Verify Timeline milestone idempotency and span termination on completion.
    
    Confirms that the first recording of a milestone mark is preserved if called again,
    and calling finish() automatically closes any in-flight open spans.
    """
    tl = Timeline()
    first = tl.mark("first_byte")
    assert tl.mark("first_byte") == first
    tl.begin("dangling")
    tl.finish()
    assert all(s.end_ms is not None for s in tl.spans)


# ---------------------------------------------------------------- core behaviour


async def test_cold_turn_both_arms_synthesize_same_text_and_no_hole_in_waterfall(tmp_path):
    """Verify cold turn behavior where both cached and uncached arms synthesize live audio.
    
    Confirms that:
    - A single LLM call supplies the identical reply text to both arms.
    - Both arms execute live TTS synthesis on cold turns.
    - Generated audio chunks are identical across arms.
    - Telemetry timeline contains no unattributed latency gaps ('holes') in the waterfall.
    - Event ordering conforms to turn_start -> reply -> audio -> arm_done -> turn_done.
    """
    pipe, store, tts, llm = build(tmp_path)
    events, by, arms, audio = await run_turn(pipe, store, "s1", Q)

    assert len(llm.calls) == 1                         # one LLM call serves both arms
    clauses = arms["cached"]["clauses"]
    assert clauses == arms["uncached"]["clauses"] >= 1  # same clauses
    assert tts.stream_calls == 2 * clauses              # cold: both arms synthesize
    assert arms["cached"]["tts_chars"] == arms["uncached"]["tts_chars"] > 0
    assert arms["cached"]["clause_hits"] == 0
    # Same bytes reach the client from both arms (fake TTS is deterministic)
    assert {i: bytes(v) for i, v in audio["cached"].items()} == {i: bytes(v) for i, v in audio["uncached"].items()}
    # The 5-second hole: every millisecond of each arm must be inside a span
    for m in arms.values():
        assert m["unattributed_ms"] < 50, m
        assert m["first_byte_ms"] <= m["first_playable_ms"] <= m["total_ms"]
    # Events arrive in a sane order
    assert [e["type"] for e in events][:2] == ["turn_start", "reply"]
    assert events[-1]["type"] == "turn_done"


async def test_exact_repeat_hits_llm_cache_and_audio_cache(tmp_path):
    """Verify that repeated queries reuse cached LLM text and pre-synthesized audio.
    
    Tests that repeating an inquiry hits the session response cache (0 additional LLM calls)
    and the audio cache (0 live TTS calls for the cached arm), while the uncached arm
    pays the full cost of re-synthesizing all clauses.
    """
    pipe, store, tts, llm = build(tmp_path)
    await run_turn(pipe, store, "s1", Q)
    calls_before = tts.stream_calls

    _, by, arms, _ = await run_turn(pipe, store, "s1", Q.lower().rstrip("?"))  # normalizes to same query
    assert by["reply"][0]["source"] == "exact_hit"
    assert len(llm.calls) == 1                         # LLM not called again
    n = arms["cached"]["clauses"]
    assert arms["cached"]["tts_calls"] == 0 and arms["cached"]["tts_chars"] == 0
    assert arms["cached"]["clause_hits"] == n
    assert arms["uncached"]["tts_calls"] == n          # no-cache arm pays again
    assert tts.stream_calls == calls_before + n
    assert by["turn_done"][0]["turn_summary"]["saved_chars"] == arms["uncached"]["tts_chars"]


async def test_hit_is_faster_than_live_on_first_playable(tmp_path):
    """Verify that serving from cache yields a significantly lower time-to-first-playable.
    
    Compares the first_playable_ms metric of the cached arm against the live uncached arm
    on a warm cache turn to prove latency reduction.
    """
    pipe, store, _, _ = build(tmp_path)
    await run_turn(pipe, store, "s1", Q)
    _, _, arms, _ = await run_turn(pipe, store, "s1", Q)
    assert arms["cached"]["first_playable_ms"] < arms["uncached"]["first_playable_ms"]


async def test_sessions_are_isolated_so_turn_one_is_always_cold(tmp_path):
    """Verify session isolation ensuring cross-caller cache privacy.
    
    Ensures that caller Bob cannot access caller Alice's session-scoped cache,
    meaning turn 1 for any new session always executes cold even if the text matches.
    """
    pipe, store, tts, _ = build(tmp_path)
    await run_turn(pipe, store, "alice", Q)
    _, by, arms, _ = await run_turn(pipe, store, "bob", Q)     # same text, other session
    assert by["reply"][0]["source"] == "llm"                   # bob's LLM cache is empty
    assert arms["cached"]["clause_hits"] == 0                  # bob's audio cache is empty
    assert arms["cached"]["tts_calls"] == arms["cached"]["clauses"]


async def test_semantic_hit_in_llm_layer(tmp_path):
    """Verify semantic similarity lookup in the session LLM response cache.
    
    Confirms that paraphrased inquiries ('how do I pay' vs 'how can I pay') that exceed
    the cosine similarity threshold achieve a semantic hit, avoiding redundant LLM generation.
    """
    pipe, store, _, llm = build(tmp_path, threshold=0.5)
    await run_turn(pipe, store, "s1", "how do I pay my electricity bill online")
    _, by, arms, _ = await run_turn(pipe, store, "s1", "how can I pay my electricity bill online")
    assert by["reply"][0]["source"] == "semantic_hit"
    assert by["reply"][0]["sim_score"] >= 0.5
    assert len(llm.calls) == 1
    assert arms["cached"]["tts_calls"] == 0


async def test_personalized_replies_never_enter_the_llm_cache(tmp_path):
    """Verify that private account or billing inquiries bypass the semantic response cache.
    
    Guarantees that routing decisions marked as 'personalized' are flagged as uncacheable,
    forcing live LLM generation for every turn to prevent data leakage between interactions.
    """
    pipe, store, _, llm = build(tmp_path, router=StubRouter("personalized"))
    await run_turn(pipe, store, "s1", "what is my bill")
    _, by, _, _ = await run_turn(pipe, store, "s1", "what is my bill")
    assert by["reply"][0]["source"] == "llm_uncacheable"
    assert len(llm.calls) == 2


async def test_intent_cache_skips_the_llm(tmp_path):
    """Verify that matched catalog intents serve canonical answers with 0 LLM calls.
    
    Tests that a routing decision of 'cached_intent' immediately supplies the canonical
    reply text without calling the LLM adapter.
    """
    pipe, store, _, llm = build(tmp_path, router=StubRouter("cached_intent", canonical="Office hours are 10 to 5."))
    _, by, arms, _ = await run_turn(pipe, store, "s1", "office hours?")
    assert by["reply"][0]["source"] == "intent_cache"
    assert len(llm.calls) == 0
    assert by["turn_done"][0]["session"]["llm"]["intent_hits"] == 1


# ---------------------------------------------------------------- guardrails


async def test_char_budget_skips_audio_but_not_the_reply(tmp_path):
    """Verify character budget exhaustion behavior.
    
    Confirms that when the remaining TTS character budget is insufficient for synthesis,
    the pipeline still yields the text reply but halts audio generation with a cap event.
    """
    pipe, store, tts, _ = build(tmp_path)
    events, by, _, _ = await run_turn(pipe, store, "s1", Q, budget=10)
    assert by["reply"] and by["cap"][0]["reason"] == "chars"
    assert tts.stream_calls == 0


async def test_turn_limit(tmp_path):
    """Verify enforcement of the maximum turn threshold per session.
    
    Ensures that exceeding max_turns terminates processing with a turn-cap event,
    preventing infinite loops or session abuse.
    """
    pipe, store, _, _ = build(tmp_path, max_turns=1)
    await run_turn(pipe, store, "s1", Q)
    _, by, _, _ = await run_turn(pipe, store, "s1", "another question")
    assert by["cap"][0]["reason"] == "turns"


async def test_failing_uncached_arm_does_not_break_the_cached_arm(tmp_path):
    """Verify error isolation between pipeline arms during TTS failures.
    
    Tests that an HTTP 500 failure during live synthesis on the uncached arm does not crash
    the turn; the cached arm successfully serves cached audio while reporting the uncached error.
    """
    pipe, store, tts, _ = build(tmp_path)
    await run_turn(pipe, store, "s1", Q)              # warm the cache
    tts.fail_with_status = 500                         # now any live synthesis fails
    _, by, arms, _ = await run_turn(pipe, store, "s1", Q)
    assert arms["cached"]["error"] is None and arms["cached"]["tts_calls"] == 0
    assert arms["uncached"]["error"] is not None
    assert by["turn_done"][0]["turn_summary"]["compared"] is False


async def test_session_totals_equal_sum_of_turns(tmp_path):
    """Verify consistency of cumulative session-level metric snapshots.
    
    Validates that the cumulative character and credit savings tracked across multiple turns
    in pipe.snapshot() accurately equal the sum of savings recorded in each turn summary.
    """
    pipe, store, _, _ = build(tmp_path)
    saved = 0
    for q in (Q, Q, "How can I report a fire hazard near a meter?"):
        _, by, _, _ = await run_turn(pipe, store, "s1", q)
        saved += by["turn_done"][0]["turn_summary"]["saved_chars"]
    snap = pipe.snapshot(store.get_or_create("s1"))
    assert snap["saved"]["tts_chars"] == saved
    assert snap["arms"]["uncached"]["tts_chars"] - snap["arms"]["cached"]["tts_chars"] == saved


def test_clip_reply():
    """Verify sentence boundary clipping logic and length constraint enforcement.
    
    Tests that clip_reply trims long responses to fit within max character thresholds
    while preserving clean sentence boundaries ending in punctuation.
    """
    assert clip_reply("Short.", 50) == "Short."
    long = "First sentence here. Second sentence here. Third sentence here."
    assert clip_reply(long, 45) == "First sentence here. Second sentence here."
    assert clip_reply("x" * 300, 100).endswith(".") and len(clip_reply("x" * 300, 100)) <= 101
