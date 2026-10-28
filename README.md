# ⚡ Gnani Voice Gateway

> A high-performance semantic response and exact audio caching layer for conversational voice agents, built for the Gnani AI Hackathon.
> Demo domain: Fictional power-utility helpline in Kolkata (Hindi, Bengali, Benglish).

---

## 🎯 What Problem This Solves

In repetitive enterprise customer support flows (power cut notifications, billing procedures, office hours, safety hazards), voice agents repeatedly transcribe identical questions, prompt an LLM to generate nearly identical replies, and synthesize identical audio clips. 

This causes two major issues:
1. **High Latency**: Callers wait 1–2+ seconds for STT, LLM inference, and TTS speech synthesis before hearing a single sound.
2. **Wasteful Character & Credit Spend**: Paid API quotas are consumed synthesizing identical sentences again and again.

**Gnani Voice Gateway** introduces an intelligent two-tier caching and streaming architecture:
- **Semantic Response Cache**: Matches fuzzy caller queries to verified canonical reply text (skipping LLM inference).
- **Exact Audio Cache (L1/L2)**: Maps normalized reply clauses to pre-synthesized WAV clips (skipping TTS synthesis).
- **Single-Flight Request Coalescing**: When multiple callers trigger the same missing phrase simultaneously, only one upstream TTS stream is launched while followers stream from the leader's live memory buffer.
- **Streaming Clause Teeing**: Splits text at natural punctuation pauses and Indic dandas (`।`), streaming the first clause immediately (under 50ms) while subsequent clauses stream in parallel.

---

## 📊 Benchmark Telemetry (Baseline vs. Gateway)

Evaluated against 200 synthetic turns sampled from Zipf distributions at three skew levels:

| Workload Skew | TTS Chars Avoided | TTS Calls Avoided | LLM Calls Avoided | TTFA (p50) | Total Turn Duration (p50) | Clause Hit Rate |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **High Skew (FAQ Spikes)** | **73.4%** | **58.0%** | **24.0%** | **33 ms** | **52 ms** *(vs 267ms)* | **74.4%** |
| **Medium Skew (Standard)** | **63.5%** | **44.0%** | **46.0%** | **28 ms** | **53 ms** *(vs 266ms)* | **67.8%** |
| **Low Skew (Long Tail)** | **50.5%** | **28.0%** | **44.0%** | **28 ms** | **59 ms** *(vs 267ms)* | **59.1%** |

*Note: Workload is synthetic. Open-ended conversational dialog will have lower hit rates. Latency gains stem from skipping LLM and TTS calls and streaming initial clauses immediately.*

---

## 🏗️ Architecture

```
Browser (Microphone + Player + Dashboard)
   │  WebSocket (Text or 16 kHz Mono PCM WAV)
   ▼
FastAPI Gateway Engine
   ├── 1. STT Adapter ──► Gnani STT (skipped on typed input)
   ├── 2. Router ───────► Whitelisted FAQ vs Personalized vs Escalation
   ├── 3. Response Layer
   │        ├── Semantic Response Cache (multilingual embeddings)
   │        └── Tiered LLM (Groq Fast / Heavy with Gemini Flash Fallback)
   ├── 4. Clause Splitter (splits on . ? ! and Indic dandas । ॥)
   ├── 5. Exact Audio Cache
   │        ├── L1 Memory LRU (bounded by bytes)
   │        ├── L2 Disk Cache (atomic writes + temp file rename)
   │        └── Single-Flight Coalescing (Leader / Follower streams)
   └── 6. Metrics & Budget Store (SQLite persistence)
```

---

## 🔒 Budget Enforcement & Guardrails

- **Hard Budget Caps**: SQLite `BudgetTracker` pre-reserves characters before any real API call. Exceeding any bucket cap (`probe`, `dev_listening`, `seeding`, `benchmark`, `public_demo`) immediately throws `BudgetExceededError`.
- **Public Demo Limits**:
  - Max 300 characters per turn.
  - Max 600 characters per session.
  - Max 1,500 characters per IP per day.
  - Emergency Kill Switch (`KILL_SWITCH=1`): Stops live synthesis immediately; cached replies continue to be served cost-free!
- **Safe Offline Mocking**: Default configuration runs in `MOCK_APIS=1` mode to guarantee zero credit consumption during tests or development.

---

## 🚀 Quickstart & Setup

### 1. Requirements & Setup
```bash
# Clone the repository
cd Documents/Gnani_audio_caching

# Install backend dependencies (Python 3.13)
pip install -r backend/requirements.txt
```

### 2. Run the Full Offline Test Suite (Zero API Credits Used)
```bash
python -m pytest backend/tests -v
```
*All 21 unit and integration tests run 100% offline using `adapters/fake.py`.*

### 3. Run the Benchmark Suite
```bash
python bench/runner.py
```
*Outputs detailed latency and savings breakdown to `bench/results/benchmark_report.json`.*

### 4. Start the Split-Screen Demo & Dashboard
```bash
uvicorn app.main:app --reload --app-dir backend
```
Open **`http://localhost:8000`** in your browser:
- **Left Panel**: Naive baseline agent without caching.
- **Right Panel**: Accelerated voice gateway.
- **Bottom Bar**: Interactive query chips, language selector (`bn-IN`, `hi-IN`, `hi-en`), and browser push-to-talk microphone.
- **Top Tabs**: Switch between Live Demo, Telemetry Waterfall Dashboard, and Budget Tracker.

---

## 📂 Repository Layout

```
├── backend/
│   ├── app/
│   │   ├── adapters/     # gnani_tts, gnani_stt, llm, fake (mock testing)
│   │   ├── audio.py      # WAV header repair (0xFFFFFFFF placeholder fix)
│   │   ├── budget.py     # SQLite character reservation & caps
│   │   ├── cache/        # keys, audio_store (L1/L2), singleflight, tee, semantic
│   │   ├── config.py     # Centralized pydantic settings
│   │   ├── main.py       # FastAPI app & WebSocket endpoint
│   │   ├── metrics/      # recorder.py, store.py (waterfall telemetry)
│   │   ├── pipeline/     # baseline.py vs gateway.py
│   │   ├── routing/      # router.py, splitter.py, intents.py
│   │   └── static/       # Split-screen UI, styles, and in-browser WAV recorder
│   └── tests/            # 21 comprehensive offline pytest tests
├── bench/
│   ├── runner.py         # Automated benchmark evaluator across 3 skews
│   └── workload.py       # Zipfian distribution workload generator
├── data/
│   ├── eval_set.jsonl    # 150 diverse multi-language test utterances
│   └── intents.yaml      # Enterprise intents catalog (personal vs non-personal)
├── notes/
│   ├── api-findings.md   # Measured probe latencies and Gnani facts
│   └── decisions.md      # Architecture and design decision log
└── frontend/             # Next.js frontend for Vercel deployment
```
