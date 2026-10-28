"""Integration tests for Baseline and Gateway pipelines."""

import pytest
from app.adapters.fake import FakeTtsAdapter, FakeSttAdapter, FakeLlmAdapter
from app.adapters.models import TtsRequest
from app.cache.audio_store import AudioStore
from app.cache.keys import audio_key
from app.cache.semantic import SemanticCache
from app.cache.singleflight import SingleFlight
from app.metrics.store import MetricsStore
from app.pipeline.baseline import BaselinePipeline
from app.pipeline.gateway import GatewayPipeline
from app.routing.intents import IntentCatalog
from app.routing.router import Router


@pytest.fixture
def test_setup(tmp_path):
    db_file = str(tmp_path / "test_pipeline_metrics.db")
    metrics_store = MetricsStore(db_path=db_file)
    audio_store = AudioStore(cache_dir=str(tmp_path / "test_audio_cache"))
    semantic_cache = SemanticCache(threshold=0.80)
    catalog = IntentCatalog(yaml_path="data/intents.yaml")
    catalog.populate_semantic_cache(semantic_cache)
    router = Router(catalog, semantic_cache)

    fake_tts = FakeTtsAdapter(delay_ms=2)
    fake_stt = FakeSttAdapter(delay_ms=2)
    fake_llm = FakeLlmAdapter(delay_ms=2)
    voice_map = {"hi-IN": "Nalini", "bn-IN": "Kirra", "hi-en": "Poorvi"}

    baseline = BaselinePipeline(
        stt_adapter=fake_stt,
        llm_adapter=fake_llm,
        tts_adapter=fake_tts,
        metrics_store=metrics_store,
        voice_map=voice_map
    )

    gateway = GatewayPipeline(
        stt_adapter=fake_stt,
        llm_adapter=fake_llm,
        tts_adapter=fake_tts,
        router=router,
        audio_store=audio_store,
        singleflight=SingleFlight(),
        metrics_store=metrics_store,
        voice_map=voice_map
    )

    return {
        "baseline": baseline,
        "gateway": gateway,
        "fake_tts": fake_tts,
        "audio_store": audio_store,
        "voice_map": voice_map
    }


@pytest.mark.asyncio
async def test_baseline_answers_5_typed_turns(test_setup):
    baseline = test_setup["baseline"]
    queries = [
        "বিল জমা দেওয়ার নিয়ম কি?",
        "নতুন মিটারের খরচ কত?",
        "বিদ্যুৎ অফিস কখন খোলা থাকে?",
        "মিটার রিডিং কোন তারিখে হবে?",
        "কাস্টমার কেয়ার নম্বর দিন।"
    ]

    for q in queries:
        chunks = []
        metrics_event = None
        async for item in baseline.execute_turn(session_id="sess_base", lang="bn-IN", text_input=q):
            if isinstance(item, bytes):
                chunks.append(item)
            elif isinstance(item, dict) and item.get("type") == "turn_done":
                metrics_event = item

        assert len(chunks) > 0
        assert metrics_event is not None
        assert metrics_event["metrics"]["arm"] == "baseline"


@pytest.mark.asyncio
async def test_same_text_twice_gives_zero_tts_calls_second_time(test_setup):
    gateway = test_setup["gateway"]
    fake_tts = test_setup["fake_tts"]

    text = "আমাদের এলাকায় বিদ্যুৎ চলে গেছে কখন আসবে?"

    # Turn 1: Cold run -> Will synthesize audio and commit to cache
    tts_calls_start = fake_tts.stream_calls
    async for _ in gateway.execute_turn(session_id="sess_1", lang="bn-IN", text_input=text):
        pass

    tts_calls_after_turn1 = fake_tts.stream_calls
    assert tts_calls_after_turn1 > tts_calls_start

    # Turn 2: Warm run with identical text -> Must hit exact audio cache!
    turn2_metric = None
    async for item in gateway.execute_turn(session_id="sess_2", lang="bn-IN", text_input=text):
        if isinstance(item, dict) and item.get("type") == "turn_done":
            turn2_metric = item["metrics"]

    tts_calls_after_turn2 = fake_tts.stream_calls

    # Exactly zero new TTS calls occurred on turn 2!
    assert tts_calls_after_turn2 == tts_calls_after_turn1
    assert turn2_metric["tts_calls"] == 0
    assert turn2_metric["clause_hits"] >= 1


@pytest.mark.asyncio
async def test_wrong_voice_or_language_never_hits(test_setup):
    gateway = test_setup["gateway"]
    fake_tts = test_setup["fake_tts"]

    # Synthesize Hindi text in hi-IN (voice Nalini)
    hi_text = "बिजली कब आएगी?"
    async for _ in gateway.execute_turn(session_id="sess_hi", lang="hi-IN", text_input=hi_text):
        pass

    calls_after_hi = fake_tts.stream_calls

    # Query same inquiry in Bengali bn-IN (voice Kirra)
    # Must NOT hit the Hindi cache entry because keys isolate voice and language!
    bn_text = "বিদ্যুৎ কখন আসবে?"
    async for _ in gateway.execute_turn(session_id="sess_bn", lang="bn-IN", text_input=bn_text):
        pass

    calls_after_bn = fake_tts.stream_calls
    assert calls_after_bn > calls_after_hi
