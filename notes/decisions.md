# Architectural and Design Decisions Log

- **2026-10-27 | Mock-first offline testing**: Real APIs are never called during tests to protect Gnani credit limits and ensure fast deterministic CI execution.
- **2026-10-27 | Timbre-v2.5 voice selection**: Nalini (hi-IN), Kirra (bn-IN), and Poorvi (hi-en) selected as verified model-voice pairings from the probe.
- **2026-10-27 | Conservative credit conversion (300 chars/credit)**: Gnani charges ~370 chars/credit; adopting 300 chars/credit ensures the budget tracker over-counts and never overspends.
- **2026-10-27 | Explicit WAV header repair**: Both SSE and REST return placeholder lengths (0xFFFFFFFF) causing player errors; audio adapter repairs RIFF/data length before caching or serving.
- **2026-10-27 | Strict separation of semantic and exact audio caches**: Semantic cache matches fuzzy intent to canonical text (saving LLM); audio cache maps normalized text to audio (saving TTS) preventing fuzzy acoustic distortions.
- **2026-10-27 | Single-flight request deduplication**: When multiple concurrent requests hit the same missing cache key, one leader executes TTS while followers stream the growing buffer.
- **2026-10-27 | Graceful degradation**: Cache errors, router errors, or fast LLM failures degrade safely to baseline LLM and TTS rather than dropping turns.
