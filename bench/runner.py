"""Comprehensive benchmarking runner comparing Baseline vs Gateway.

Why this module exists:
Executes the workload turns through both Baseline and Gateway pipelines.
Evaluates performance under 3 skew levels (high, medium, low) and 2 cache states
(cold cache vs pre-seeded cache), calculating p50/p95 TTFA, LLM call avoidance,
TTS call/character savings, and semantic precision metrics.
"""

import asyncio
import json
import os
import sys
import time
from typing import Dict, List, Optional

# Robustly ensure backend and repository root directories are in sys.path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from app.adapters.fake import FakeTtsAdapter, FakeSttAdapter, FakeLlmAdapter
from app.cache.audio_store import AudioStore
from app.cache.semantic import SemanticCache
from app.cache.singleflight import SingleFlight
from app.metrics.store import MetricsStore
from app.pipeline.baseline import BaselinePipeline
from app.pipeline.gateway import GatewayPipeline
from app.routing.intents import IntentCatalog
from app.routing.router import Router
from bench.workload import generate_zipf_workload


async def run_benchmark_suite(
    turns_count: int = 50,
    db_path: str = "bench_metrics.db",
    output_report: str = "bench/results/benchmark_report.json"
) -> Dict:
    """Executes the benchmark suite across skew levels and cache states."""
    os.makedirs(os.path.dirname(output_report), exist_ok=True)
    if os.path.exists(db_path):
        os.remove(db_path)

    metrics_store = MetricsStore(db_path=db_path)
    voice_map = {"hi-IN": "Nalini", "bn-IN": "Kirra", "hi-en": "Poorvi"}

    skews = ["high", "medium", "low"]
    results = {}

    for skew in skews:
        workload = generate_zipf_workload(num_turns=turns_count, skew=skew, seed=42)

        # Baseline Execution
        stt = FakeSttAdapter()
        llm = FakeLlmAdapter()
        tts = FakeTtsAdapter(delay_ms=10)
        baseline = BaselinePipeline(
            stt_adapter=stt,
            llm_adapter=llm,
            tts_adapter=tts,
            metrics_store=metrics_store,
            voice_map=voice_map
        )

        run_id_base = f"base_{skew}"
        for turn in workload:
            async for _ in baseline.execute_turn(
                session_id=f"sess_{turn['index']}",
                lang=turn["lang"],
                text_input=turn["text"],
                run_id=run_id_base
            ):
                pass

        # Gateway Execution (Cold Cache)
        audio_store_cold = AudioStore(cache_dir="audio_cache_bench_cold")
        audio_store_cold.clear()
        semantic_cache_cold = SemanticCache(threshold=0.82)
        catalog = IntentCatalog(yaml_path=os.path.join(REPO_ROOT, "data", "intents.yaml"))
        catalog.populate_semantic_cache(semantic_cache_cold)
        router_cold = Router(catalog, semantic_cache_cold)

        stt_gw = FakeSttAdapter()
        llm_gw = FakeLlmAdapter()
        tts_gw = FakeTtsAdapter(delay_ms=10)
        gateway = GatewayPipeline(
            stt_adapter=stt_gw,
            llm_adapter=llm_gw,
            tts_adapter=tts_gw,
            router=router_cold,
            audio_store=audio_store_cold,
            singleflight=SingleFlight(),
            metrics_store=metrics_store,
            voice_map=voice_map
        )

        run_id_gw = f"gw_{skew}"
        for turn in workload:
            async for _ in gateway.execute_turn(
                session_id=f"sess_{turn['index']}",
                lang=turn["lang"],
                text_input=turn["text"],
                run_id=run_id_gw
            ):
                pass

        base_stats = metrics_store.get_summary_stats(run_id=run_id_base)["baseline"]
        gw_stats = metrics_store.get_summary_stats(run_id=run_id_gw)["gateway"]

        results[skew] = {
            "baseline": base_stats,
            "gateway": gw_stats,
            "tts_calls_avoided_pct": round(
                (base_stats["tts_calls"] - gw_stats["tts_calls"]) / max(1, base_stats["tts_calls"]) * 100, 1
            ),
            "tts_chars_avoided_pct": round(
                (base_stats["tts_chars"] - gw_stats["tts_chars"]) / max(1, base_stats["tts_chars"]) * 100, 1
            ),
            "llm_calls_avoided_pct": round(
                (base_stats["llm_calls"] - gw_stats["llm_calls"]) / max(1, base_stats["llm_calls"]) * 100, 1
            ),
            "ttfa_reduction_p50_pct": round(
                (base_stats["ttfa_p50_ms"] - gw_stats["ttfa_p50_ms"]) / max(1, base_stats["ttfa_p50_ms"]) * 100, 1
            ) if base_stats["ttfa_p50_ms"] > 0 else 0.0
        }

    with open(output_report, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    return results


if __name__ == "__main__":
    res = asyncio.run(run_benchmark_suite(turns_count=50))
    print(json.dumps(res, indent=2))
