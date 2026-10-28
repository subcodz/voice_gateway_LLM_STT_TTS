"""Benchmark package for Gnani Voice Gateway."""

from bench.workload import generate_zipf_workload
from bench.runner import run_benchmark_suite

__all__ = ["generate_zipf_workload", "run_benchmark_suite"]
