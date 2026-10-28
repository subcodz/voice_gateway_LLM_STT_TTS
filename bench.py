"""CLI entrypoint for running the voice gateway benchmark suite.

Why this module exists:
Provides a root-level executable script for running the benchmark workload across
high, medium, and low skew levels. It invokes the benchmarking runner in bench/runner.py,
outputting latency metrics, cache hit rates, and characters saved to the terminal and
persisting the JSON report.
"""

import argparse
import asyncio
import json
import os
import sys
import importlib.util

# Ensure repository root and backend directory are in module search path
REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# Load runner dynamically to avoid module/package name collision between bench.py and bench/
RUNNER_PATH = os.path.join(REPO_ROOT, "bench", "runner.py")
spec = importlib.util.spec_from_file_location("bench_runner_module", RUNNER_PATH)
if spec is None or spec.loader is None:
    raise ImportError(f"Could not load benchmark runner from {RUNNER_PATH}")
runner_mod = importlib.util.module_from_spec(spec)
sys.modules["bench_runner_module"] = runner_mod
spec.loader.exec_module(runner_mod)
run_benchmark_suite = runner_mod.run_benchmark_suite


def main():
    parser = argparse.ArgumentParser(description="Run Gnani Voice Gateway Benchmark Suite")
    parser.add_argument("--turns", type=int, default=50, help="Number of turns per skew arm (default: 50)")
    parser.add_argument("--db", type=str, default="bench_metrics.db", help="SQLite database path for benchmark metrics")
    parser.add_argument("--output", type=str, default="bench/results/benchmark_report.json", help="Path for JSON results")
    args = parser.parse_args()

    print(f"Starting Benchmark Suite ({args.turns} turns per arm across high, medium, low skew)...")
    results = asyncio.run(run_benchmark_suite(
        turns_count=args.turns,
        db_path=args.db,
        output_report=args.output
    ))
    print("\nBenchmark Completed Successfully! Results Summary:\n")
    print(json.dumps(results, indent=2))
    print(f"\nReport written to: {args.output}")


if __name__ == "__main__":
    main()
