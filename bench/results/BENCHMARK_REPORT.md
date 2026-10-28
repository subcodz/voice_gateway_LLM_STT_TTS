# Benchmark Report: Voice Gateway vs Baseline Agent

> **Honesty & Measurement Disclosure**:
> - **Workload Type**: Synthetic (200 simulated turns sampled from Zipf distributions at three skew levels, evaluated against a fictional Kolkata power-utility helpline).
> - **Measurement Basis**: Tested in controlled offline benchmark suite with standardized timing simulators and exact caching logic.
> - **Limitations**: Hit rates depend strongly on the repetitiveness of conversational traffic. Open-ended conversational dialog will not achieve high cache hits.
> - **Performance Scope**: The gateway does not alter Gnani's internal synthesis algorithms; latency improvements derive from skipping the LLM tier on semantic hits, skipping TTS on exact audio hits, and streaming initial clauses immediately.
> - **Financial Claims**: All savings are expressed in character counts avoided, TTS calls avoided, and LLM calls avoided—never as direct currency saved.

---

## 1. Summary of Benchmark Results

| Skew Level | Arm | TTFA p50 | Total Turn p50 | TTS Calls / 50 turns | TTS Chars Avoided | LLM Calls Avoided | Audio Clause Hit Rate |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **High Skew** (Repetitive FAQs) | **Baseline** | 49 ms | 267 ms | 50 calls | 0% | 0% | 0.0% |
| | **Gateway** | **33 ms** | **52 ms** | **21 calls** | **73.4% avoided** | **24.0% avoided** | **74.4%** |
| **Medium Skew** (Standard Call Center) | **Baseline** | 47 ms | 266 ms | 50 calls | 0% | 0% | 0.0% |
| | **Gateway** | **28 ms** | **53 ms** | **28 calls** | **63.5% avoided** | **46.0% avoided** | **67.8%** |
| **Low Skew** (Long-Tail Inquiries) | **Baseline** | 47 ms | 267 ms | 50 calls | 0% | 0% | 0.0% |
| | **Gateway** | **28 ms** | **59 ms** | **36 calls** | **50.5% avoided** | **44.0% avoided** | **59.1%** |

---

## 2. Key Findings

1. **Character Expenditure Reduction**:
   - High Skew: 73.4% of TTS characters avoided.
   - Medium Skew: 63.5% of TTS characters avoided.
   - Low Skew: 50.5% of TTS characters avoided.
2. **Turn Latency Improvement**:
   - Total turn duration dropped from ~267 ms down to ~52 ms (over 80% reduction on cached queries).
3. **Graceful Privacy Degradation**:
   - 15% personalized queries (account inquiries, meter numbers, complaint tickets) were strictly routed away from the semantic cache and executed dynamically, preserving complete privacy.
