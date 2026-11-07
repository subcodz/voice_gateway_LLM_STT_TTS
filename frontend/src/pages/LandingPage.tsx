import React, { useState, useEffect } from 'react';
import { TurnSimulation } from '../components/TurnSimulation';
import { CostCalculator } from '../components/CostCalculator';
import { ArchitectureDiagram } from '../components/ArchitectureDiagram';
import { PixelDispersalPattern } from '../components/PixelDispersalPattern';

interface LandingPageProps {
  onNavigate: (path: string) => void;
}

const GUARDRAIL_EXAMPLES = [
  { text: 'what is my meter number', route: 'personalized' },
  { text: 'office timings please', route: 'cached_intent' },
  { text: 'I want compensation', route: 'heavy_llm' },
  { text: 'bijli kab aayegi', route: 'cached_intent' },
];

const TECH_STACK = [
  { layer: 'Text to speech', provider: 'Gnani Vachana', model: 'timbre-v2.5', desc: 'SSE streaming and REST inference at 48 kHz mono. Voices Nalini (hi-IN), Kirra (bn-IN), Poorvi (hi-en).' },
  { layer: 'Speech to text', provider: 'Gnani Vachana', model: '/stt/v3', desc: 'Transcribes caller audio with language tagging.' },
  { layer: 'Embeddings', provider: 'Hugging Face (sentence-transformers)', model: 'intfloat/multilingual-e5-small', desc: 'Runs on CPU with query and passage prefixes. Drives intent matching and the session response cache.' },
  { layer: 'Fast LLM', provider: 'Groq', model: 'llama-3.1-8b-instant', desc: 'Default tier for non-cached, non-escalated queries.' },
  { layer: 'Heavy LLM', provider: 'Groq', model: 'llama-3.3-70b-versatile', desc: 'Escalations, and fallback when the fast tier fails.' },
  { layer: 'LLM fallback', provider: 'Google Gemini', model: 'gemini-2.5-flash', desc: 'Used when Groq rate-limits or times out.' },
  { layer: 'Backend', provider: 'FastAPI, httpx, WebSocket', model: 'Python, Pydantic, SQLite', desc: 'Async pipeline, per-session cache namespaces, budget buckets, per-IP and per-session spend caps.' },
];

export const LandingPage: React.FC<LandingPageProps> = ({ onNavigate }) => {
  // Single-flight dots animation
  const [callerCount, setCallerCount] = useState<number>(1);
  useEffect(() => {
    const timer = setInterval(() => {
      setCallerCount((prev) => (prev % 10) + 1);
    }, 450);
    return () => clearInterval(timer);
  }, []);

  // Guardrail text cycling
  const [guardrailIdx, setGuardrailIdx] = useState<number>(0);
  useEffect(() => {
    const timer = setInterval(() => {
      setGuardrailIdx((prev) => (prev + 1) % GUARDRAIL_EXAMPLES.length);
    }, 2000);
    return () => clearInterval(timer);
  }, []);

  const curGuard = GUARDRAIL_EXAMPLES[guardrailIdx];

  return (
    <div className="flex flex-col min-h-screen">
      {/* Hero Section with Upward Radial Spotlight */}
      <header className="relative pt-16 pb-16 text-center overflow-hidden">
        {/* Spotlight pseudo overlay */}
        <div
          className="absolute inset-0 pointer-events-none z-0"
          style={{ background: 'var(--hero-spotlight)' }}
        />

        <div className="relative z-10 max-w-[1120px] mx-auto px-6">
          <div className="inline-flex items-center gap-2 text-xs text-zinc-300 px-3.5 py-1.5 inset-shadow-lg inset-shadow-neutral-500 rounded-full mb-6 ">
            <span className="w-1.5 h-1.5 rounded-full bg-white inline-block" />
            Voice gateway for Hindi, Bengali and Hinglish
          </div>

          <h1 className="text-4xl sm:text-6xl md:text-7xl tracking-tight text-white max-w-[860px] mx-auto leading-[1.05]">
            Stop paying to synthesize the same sentence twice.
          </h1>

          <p className="mt-5 text-base sm:text-lg text-zinc-400 max-w-[620px] mx-auto leading-relaxed">
            CacheBuddy sits between your callers and your speech stack. It routes, caches and streams audio so repeated answers cost nothing and start playing in milliseconds.
          </p>

          <div className="flex flex-wrap gap-3 justify-center mt-8">
            <button
              onClick={() => onNavigate('/session')}
              className="px-5 py-2.5 rounded-lg inset-shadow-lg inset-shadow-neutral-900 bg-white text-black font-semibold text-sm hover:bg-zinc-200 transition-all flex items-center gap-2 "
            >
              Try the session demo →
            </button>
            <a
              href="#architecture"
              className="px-5 py-2.5 rounded-lg border border-white/20 inset-shadow-lg inset-shadow-blue-900 text-white font-medium text-sm hover:bg-white/10 transition-colors"
            >
              Explore the architecture
            </a>
          </div>

          <div className="mt-14">
            <TurnSimulation />
          </div>
        </div>
      </header>

      {/* Stats Ribbon */}
      <section className="border-y border-white/[0.09] bg-zinc-950/40">
        <div className="max-w-[1120px] mx-auto px-6 grid grid-cols-2 md:grid-cols-4 divide-y md:divide-y-0 md:divide-x divide-white/[0.09]">
          <div className="py-6 px-4">
            <b className="block text-3xl font-bold tracking-tight text-white font-mono">2</b>
            <span className="text-xs text-zinc-400">cache tiers, memory LRU & atomic disk</span>
          </div>
          <div className="py-6 px-4">
            <b className="block text-3xl font-bold tracking-tight text-white font-mono">3</b>
            <span className="text-xs text-zinc-400">routes: cached, personalized, heavy LLM</span>
          </div>
          <div className="py-6 px-4">
            <b className="block text-3xl font-bold tracking-tight text-white font-mono">1</b>
            <span className="text-xs text-zinc-400">upstream call for N identical requests</span>
          </div>
          <div className="py-6 px-4">
            <b className="block text-3xl font-bold tracking-tight text-white font-mono">0</b>
            <span className="text-xs text-zinc-400">personal answers ever cached</span>
          </div>
        </div>
      </section>

      {/* Features Bento Grid */}
      <section id="features" className="py-24">
        <div className="max-w-[1120px] mx-auto px-6">
          <div className="text-xs font-semibold tracking-wider uppercase text-zinc-400 mb-3">
            Features
          </div>
          <h2 className="text-3xl sm:text-4xl tracking-tight text-white max-w-[680px]">
            Built to take cost and latency out of the loop.
          </h2>

          <div className="grid grid-cols-1 md:grid-cols-6 gap-4 mt-12">
            {/* Cost Calculator - 4 Cols */}
            <div className="md:col-span-4">
              <CostCalculator />
            </div>

            {/* Time to first sound - 2 Cols */}
            <div className="md:col-span-2 shiny-card p-6 rounded-2xl flex flex-col justify-between">
              <div>
                <h3 className="text-lg font-semibold tracking-tight text-white mb-2">Time to first sound</h3>
                <p className="text-sm text-zinc-400 mb-6">
                  Live TTS streams its first chunk in ~520 to 740 ms in our probes. A cache hit skips network latency.
                </p>
              </div>

              <div className="space-y-4">
                <div>
                  <div className="flex justify-between text-xs font-mono text-zinc-400 mb-1.5">
                    <span>Live synthesis</span>
                    <span>~600 ms</span>
                  </div>
                  <div className="h-2.5 bg-zinc-800 rounded-full overflow-hidden">
                    <div className="h-full bg-zinc-500 rounded-full w-full" />
                  </div>
                </div>

                <div>
                  <div className="flex justify-between text-xs font-mono text-zinc-400 mb-1.5">
                    <span>Cache hit (target)</span>
                    <span className="text-emerald-400 font-semibold">&lt; 50 ms</span>
                  </div>
                  <div className="h-2.5 bg-zinc-800 rounded-full overflow-hidden">
                    <div className="h-full bg-white rounded-full w-[10%]" />
                  </div>
                </div>
              </div>
            </div>

            {/* Single-flight Dedup - 2 Cols */}
            <div className="md:col-span-2 shiny-card p-6 rounded-2xl flex flex-col justify-between">
              <div>
                <h3 className="text-lg font-semibold tracking-tight text-white mb-2">Single-flight dedup</h3>
                <p className="text-sm text-zinc-400 mb-5">
                  Ten callers ask for the same new phrase. One leader synthesizes; the rest follow its buffer.
                </p>
              </div>

              <div>
                <div className="flex items-center gap-1.5 mb-3 flex-wrap">
                  {Array.from({ length: 10 }).map((_, i) => (
                    <span
                      key={i}
                      className={`w-3.5 h-3.5 rounded transition-all duration-300 ${i < callerCount ? 'bg-white scale-105' : 'bg-zinc-800'
                        }`}
                    />
                  ))}
                </div>
                <div className="text-xs font-mono px-3 py-1.5 rounded-lg border border-white/10 bg-zinc-900 inline-block text-zinc-300">
                  Callers: {callerCount} · TTS calls: 1
                </div>
              </div>
            </div>

            {/* Personal Data Guardrail - 2 Cols */}
            <div className="md:col-span-2 shiny-card p-6 rounded-2xl flex flex-col justify-between">
              <div>
                <h3 className="text-lg font-semibold tracking-tight text-white mb-2">Personal data guardrail</h3>
                <p className="text-sm text-zinc-400 mb-5">
                  Rule-based, word-aware, fail-closed. Account queries never touch a shared cache.
                </p>
              </div>

              <div className="p-3 rounded-xl bg-zinc-900/90 border border-white/10 flex justify-between items-center text-xs">
                <span className="text-zinc-200">{curGuard.text}</span>
                <span className="font-mono text-[11px] bg-white text-black px-2 py-0.5 rounded font-semibold">
                  {curGuard.route}
                </span>
              </div>
            </div>

            {/* Clean Audio - 2 Cols */}
            <div className="md:col-span-2 shiny-card p-6 rounded-2xl flex flex-col justify-between">
              <div>
                <h3 className="text-lg font-semibold tracking-tight text-white mb-2">Clean audio, always</h3>
                <p className="text-sm text-zinc-400 leading-relaxed">
                  Streamed WAVs arrive with 0xFFFFFFFF length placeholders. Headers are repaired before caching so every clip plays cleanly.
                </p>
              </div>
              <div className="text-xs font-mono text-zinc-400 pt-2 border-t border-white/[0.08]">
                Auto WAV Header Recovery
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Architecture Section */}
      <section id="architecture" className="py-24 border-t border-white/[0.09]">
        <div className="max-w-[1120px] mx-auto px-6">
          <div className="text-xs font-semibold tracking-wider uppercase text-zinc-400 mb-3">
            Architecture
          </div>
          <h2 className="text-3xl sm:text-4xl tracking-tight text-white max-w-[680px]">
            One turn, end to end. Hover any stage.
          </h2>
          <p className="text-sm sm:text-base text-zinc-400 mt-3">
            Hover any stage to inspect what it does, why it exists, and its latency role.
          </p>

          <ArchitectureDiagram />
        </div>
      </section>

      {/* Technology Section */}
      <section id="stack" className="py-24 border-t border-white/[0.09]">
        <div className="max-w-[1120px] mx-auto px-6">
          <div className="text-xs font-semibold tracking-wider uppercase text-zinc-400 mb-3">
            Technology
          </div>
          <h2 className="text-3xl sm:text-4xl tracking-tight text-white mb-6">
            What is running under the hood today.
          </h2>

          <div className="shiny-card rounded-2xl overflow-hidden divide-y divide-white/[0.08]">
            {/* Header row */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 p-4 text-[11px] font-mono uppercase tracking-wider text-zinc-400 bg-zinc-900/60 font-semibold">
              <span>Layer</span>
              <span>Provider</span>
              <span>Model / component</span>
              <span>Role</span>
            </div>

            {/* Data rows */}
            {TECH_STACK.map((row) => (
              <div key={row.layer} className="grid grid-cols-1 md:grid-cols-4 gap-1 p-4 text-sm hover:bg-white/[0.02] transition-colors">
                <span className="font-semibold text-white">{row.layer}</span>
                <span className="text-zinc-300">{row.provider}</span>
                <span className="font-mono text-xs px-2 py-0.5 rounded w-fit text-zinc-200">
                  {row.model}
                </span>
                <span className="text-xs sm:text-sm text-zinc-400 leading-relaxed">{row.desc}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Final CTA Card */}
      <section className="py-20">
        <div className="max-w-[1072px] mx-auto px-6">
          <div className="shiny-card p-12 text-center rounded-3xl relative overflow-hidden">
            {/* Bottom-to-top monochrome pixel dispersion pattern */}
            <PixelDispersalPattern />

            <div className="relative z-10">
              <h2 className="text-3xl sm:text-4xl tracking-tight text-white mb-3">
                See the cache pay for itself in five turns.
              </h2>
              <p className="text-sm sm:text-base text-zinc-400 max-w-[560px] mx-auto mb-8 leading-relaxed">
                The session demo runs both audio paths side by side on the same reply text with live audio streaming.
              </p>
              <button
                onClick={() => onNavigate('/session')}
                className="px-6 py-3 rounded-xl bg-white text-black font-semibold text-sm hover:bg-zinc-200 transition-colors shadow-xl"
              >
                Open the live demo →
              </button>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
};

