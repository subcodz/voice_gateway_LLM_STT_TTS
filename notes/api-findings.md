# Gnani API Findings & Probe Analysis

## Verified API Facts
- **Base URL**: `https://api.vachana.ai`
- **Auth Header**: `X-API-Key-ID: <key>`
- **TTS REST Endpoint**: `POST /api/v1/tts/inference`
- **TTS SSE Endpoint**: `POST /api/v1/tts/sse`
- **STT Endpoint**: `POST /stt/v3` (multipart `audio_file`, `language_code`, `format=transcribe`)

## Probe Measurements (from probe_log.jsonl)
- **Model**: `timbre-v2.5`
- **Sample Rate**: 48,000 Hz, 16-bit mono PCM WAV
- **Voices Tested**:
  - `hi-IN`: Nalini
  - `bn-IN`: Kirra
  - `hi-en` (Hinglish): Poorvi
- **Latencies**:
  - **SSE First-chunk TTFA**: ~519ms - 736ms (connection reuse average ~600ms)
  - **SSE Total audio stream**: ~880ms - 1,450ms
  - **REST Whole clip**: ~960ms - 1,380ms
- **WAV Header Issue**:
  - Both SSE and REST return a RIFF header with placeholder length `0xFFFFFFFF` (4,294,967,295 bytes). Python's standard `wave` library misinterprets this as thousands of seconds.
  - Fix: `app/audio.py::fix_wav_header` patches the RIFF and data chunk byte lengths to match exact byte length.
- **Audio Output Size**:
  - ~290 KB - 415 KB for 3-4 second clips at 48kHz mono 16-bit.
- **Billing Ratio**:
  - Measured 971 characters used ~3 credits, matching ~370 characters per credit.
  - BudgetTracker uses a conservative 300 characters per credit to ensure caps are never breached.
