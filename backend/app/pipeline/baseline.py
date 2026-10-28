"""Naive baseline voice agent pipeline without caching or optimization.

Why this module exists:
Serves as the rigorous control arm for benchmarks and split-screen comparisons.
It processes turns sequentially through STT, LLM, and TTS with no semantic response
caching, no audio caching, and no clause splitting, providing an honest baseline for
speed and credit consumption under identical network conditions.
"""

import time
from typing import AsyncIterator, Optional, Tuple, Union
from app.adapters.models import Msg, TtsRequest, TtsStats
from app.metrics.recorder import TurnRecorder
from app.metrics.store import MetricsStore, TurnMetric


class BaselinePipeline:
    def __init__(
        self,
        stt_adapter,
        llm_adapter,
        tts_adapter,
        metrics_store: MetricsStore,
        voice_map: dict[str, str],
        model: str = "timbre-v2.5",
        sample_rate: int = 48000
    ):
        self.stt_adapter = stt_adapter
        self.llm_adapter = llm_adapter
        self.tts_adapter = tts_adapter
        self.metrics_store = metrics_store
        self.voice_map = voice_map
        self.model = model
        self.sample_rate = sample_rate

    async def execute_turn(
        self,
        session_id: str,
        lang: str = "bn-IN",
        text_input: Optional[str] = None,
        wav_input: Optional[bytes] = None,
        run_id: str = "default"
    ) -> AsyncIterator[Union[dict, bytes]]:
        """Executes a turn through the naive baseline pipeline.
        
        Yields:
        - {"type": "transcript", "text": transcript} (if wav_input)
        - {"type": "route", "decision": "baseline", "sim_score": 0.0}
        - {"type": "reply_text", "text": reply_text}
        - bytes (audio chunks from TTS)
        - {"type": "turn_done", "metrics": TurnMetric.dict()}
        """
        recorder = TurnRecorder(
            store=self.metrics_store,
            arm="baseline",
            session_id=session_id,
            lang=lang,
            run_id=run_id
        )

        transcript = text_input or ""

        # Step 1: STT if audio provided
        if wav_input and not text_input:
            t0 = time.perf_counter()
            res = await self.stt_adapter.transcribe(wav_input, lang=lang)
            stt_ms = round((time.perf_counter() - t0) * 1000)
            recorder.record_stt(stt_ms)
            transcript = res.text
            yield {"type": "transcript", "text": transcript}

        yield {"type": "route", "decision": "baseline", "sim_score": 0.0}

        # Step 2: Call LLM (Fast tier)
        t0 = time.perf_counter()
        history = [Msg(role="user", content=transcript)]
        reply_text = await self.llm_adapter.reply(history, tier="fast")
        llm_ms = round((time.perf_counter() - t0) * 1000)
        recorder.record_llm(llm_ms, calls=1)

        yield {"type": "reply_text", "text": reply_text}

        # Step 3: Call TTS without caching or clause splitting
        voice = self.voice_map.get(lang, "Kirra")
        req = TtsRequest(
            text=reply_text,
            voice=voice,
            model=self.model,
            language=lang,
            sample_rate=self.sample_rate
        )

        tts_stats = TtsStats()
        async for chunk in self.tts_adapter.stream(req, stats=tts_stats):
            recorder.record_ttfa()
            yield chunk

        recorder.record_clause(hit=False, chars=len(reply_text), is_tts_call=True)
        if tts_stats.retries > 0:
            for _ in range(tts_stats.retries):
                recorder.record_retry()

        metrics = recorder.finish()
        yield {"type": "turn_done", "metrics": metrics.model_dump()}
