import React, { useState, useEffect, useRef } from 'react';

interface ArchNode {
  id: string;
  x: number;
  y: number;
  a: string;
  b: string;
  t: string;
  h: string;
  p: string;
  l: [string, string][];
}

const NODES: ArchNode[] = [
  {
    id: "caller", x: 20, y: 30, a: "Caller", b: "audio in", t: "Entry", h: "Caller audio",
    p: "A caller speaks, or types in the demo. Audio is captured as 16 kHz mono WAV and handed to speech recognition.",
    l: [["Input", "16 kHz mono WAV"], ["Languages", "hi-IN, bn-IN, hi-en"]]
  },
  {
    id: "stt", x: 200, y: 30, a: "STT", b: "Gnani /stt/v3", t: "Speech to text", h: "Speech recognition",
    p: "Multipart upload to Gnani’s v3 transcription endpoint. The adapter tolerates several response shapes, and reserves budget up front, refunding it if the call fails.",
    l: [["Endpoint", "POST /stt/v3"], ["Bucket", "stt_testing"]]
  },
  {
    id: "router", x: 380, y: 30, a: "Router", b: "rules + semantic", t: "Decision", h: "Router and semantic cache",
    p: "Rules run first and fail closed: personal account language goes to a live LLM and is never cached, escalation language goes to the heavy tier. Otherwise the embedding model matches the query to a whitelisted intent.",
    l: [["Embedder", "multilingual-e5-small"], ["Threshold", "0.82 (demo 0.90)"], ["Rules", "data/routing_rules.yaml"]]
  },
  {
    id: "llm", x: 560, y: 30, a: "LLM layer", b: "cache, then model", t: "Reply text", h: "LLM layer",
    p: "Order of preference: intent canonical reply, session response cache (exact then semantic), then a live model. Fast tier falls back to heavy, then to Gemini.",
    l: [["Fast", "llama-3.1-8b-instant"], ["Heavy", "llama-3.3-70b-versatile"], ["Fallback", "gemini-2.5-flash"]]
  },
  {
    id: "split", x: 740, y: 30, a: "Clause splitter", b: "danda aware", t: "Segmentation", h: "Clause splitter",
    p: "Replies are split on . ? ! and the Hindi/Bengali danda, with soft splits at commas for long clauses. Short, reusable clauses mean the first one can be cached and played while the rest synthesize.",
    l: [["Max clause", "120 chars"], ["Benefit", "Partial reuse"]]
  },
  {
    id: "cache", x: 740, y: 170, a: "Audio cache", b: "L1 RAM · L2 disk", t: "Storage", h: "Two-tier audio cache",
    p: "Keys are SHA-256 over version, model, voice, language, speed, sample rate and normalized text. Hot clips come from a memory LRU, the rest from disk. Writes are temp-file plus atomic rename.",
    l: [["L1", "64 MB LRU"], ["L2", "256 MB disk, LRU"], ["Empty clips", "Never written"]]
  },
  {
    id: "sf", x: 560, y: 170, a: "Single-flight", b: "leader + followers", t: "Concurrency", h: "Single-flight coalescing",
    p: "On a miss, the first request becomes the leader and calls TTS. Concurrent identical requests stream from the leader’s live buffer instead of paying again, and retry directly if the leader fails.",
    l: [["10 identical", "1 TTS call"], ["Failure", "Follower retries once"]]
  },
  {
    id: "tts", x: 380, y: 170, a: "Gnani TTS", b: "timbre-v2.5 · SSE", t: "Synthesis", h: "Streaming synthesis",
    p: "SSE endpoint with base64 chunks. Transient 429 and 5xx errors retry with backoff only before audio starts. A 403 is never retried. Characters are reserved first.",
    l: [["Voices", "Nalini · Kirra · Poorvi"], ["Format", "48 kHz 16-bit mono"], ["First chunk", "~520–740 ms"]]
  },
  {
    id: "tee", x: 200, y: 170, a: "Tee + repair", b: "stream and commit", t: "Streaming", h: "Tee and WAV repair",
    p: "Chunks go to the client as they arrive while being buffered. On a clean finish the RIFF and data sizes are rewritten from the 0xFFFFFFFF placeholder, then the clip is committed.",
    l: [["Commit", "Only on complete"], ["Header", "RIFF + data patched"]]
  },
  {
    id: "client", x: 20, y: 170, a: "Client", b: "gapless playback", t: "Delivery", h: "Playback",
    p: "The browser receives paired header and binary frames over one WebSocket, assembles each clause, repairs the header locally, and plays clause by clause.",
    l: [["Transport", "WebSocket"], ["Order", "Clause by clause"]]
  },
  {
    id: "budget", x: 380, y: 310, a: "Budget tracker", b: "SQLite buckets", t: "Guardrail", h: "Budget and kill switch",
    p: "Every paid call reserves characters against a bucket cap first. Over-cap calls are refused, failures are refunded, and a global kill switch suspends live calls.",
    l: [["Counted at", "300 chars / credit"], ["Measured", "~370 chars / credit"]]
  }
];

const EDGES: [number, number, number, number][] = [
  [170, 58, 200, 58], [350, 58, 380, 58], [530, 58, 560, 58], [710, 58, 740, 58],
  [815, 86, 815, 170], [740, 198, 710, 198], [560, 198, 530, 198], [380, 198, 350, 198],
  [200, 198, 170, 198], [455, 226, 455, 310]
];

const ZOOM_HEIGHT = 280; // Deep zoom fitting the whole card (~2.8x magnification)

// Cubic bezier evaluator for smooth cinematics
function cubicBezier(p1x: number, p1y: number, p2x: number, p2y: number) {
  return function (t: number): number {
    if (t <= 0) return 0;
    if (t >= 1) return 1;
    let u = t;
    for (let i = 0; i < 8; i++) {
      const x = 3 * (1 - u) * (1 - u) * u * p1x + 3 * (1 - u) * u * u * p2x + u * u * u;
      const dx = 3 * (1 - u) * (1 - u) * p1x + 6 * (1 - u) * u * (p2x - p1x) + 3 * u * u * (1 - p2x);
      if (Math.abs(x - t) < 1e-5) break;
      u -= (x - t) / (dx || 1);
    }
    return 3 * (1 - u) * (1 - u) * u * p1y + 3 * (1 - u) * u * u * p2y + u * u * u;
  };
}

const easeInOutCubic = cubicBezier(0.4, 0.0, 0.2, 1.0);

export const ArchitectureDiagram: React.FC = () => {
  const [activeIdx, setActiveIdx] = useState<number | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const [aspect, setAspect] = useState<number>(640 / 380);

  // Measure card aspect ratio dynamically to ensure 100% full-bleed coverage
  useEffect(() => {
    const updateAspect = () => {
      if (cardRef.current) {
        const w = cardRef.current.clientWidth || 640;
        const h = cardRef.current.clientHeight || 380;
        setAspect(w / h);
      }
    };
    updateAspect();
    window.addEventListener('resize', updateAspect);
    return () => window.removeEventListener('resize', updateAspect);
  }, []);

  // Compute idle viewBox matching container aspect ratio so it fills 100% of card
  const getIdleViewBox = (ratio: number) => {
    const w = 940;
    const h = w / ratio;
    const x = -10;
    const y = 190 - h / 2;
    return { x, y, w, h };
  };

  const [viewBox, setViewBox] = useState<{ x: number; y: number; w: number; h: number }>(() => getIdleViewBox(aspect));
  const animRef = useRef<number | null>(null);
  const currentVb = useRef(getIdleViewBox(aspect));
  const hoverTimer = useRef<number | null>(null);

  useEffect(() => {
    let targetX = 0;
    let targetY = 0;
    let targetW = 0;
    let targetH = 0;

    if (activeIdx !== null) {
      const n = NODES[activeIdx];
      targetH = ZOOM_HEIGHT;
      targetW = targetH * aspect;
      const cx = n.x + 75;
      const cy = n.y + 28;
      targetX = cx - targetW / 2;
      targetY = cy - targetH / 2;
    } else {
      const idle = getIdleViewBox(aspect);
      targetX = idle.x;
      targetY = idle.y;
      targetW = idle.w;
      targetH = idle.h;
    }

    const startX = currentVb.current.x;
    const startY = currentVb.current.y;
    const startW = currentVb.current.w;
    const startH = currentVb.current.h;
    const startTime = performance.now();
    const duration = 650; // smooth 520ms glide

    const animate = (now: number) => {
      const elapsed = now - startTime;
      const progress = Math.min(1, elapsed / duration);
      const eased = easeInOutCubic(progress);

      const curX = startX + (targetX - startX) * eased;
      const curY = startY + (targetY - startY) * eased;
      const curW = startW + (targetW - startW) * eased;
      const curH = startH + (targetH - startH) * eased;

      currentVb.current = { x: curX, y: curY, w: curW, h: curH };
      setViewBox({ x: curX, y: curY, w: curW, h: curH });

      if (progress < 1) {
        animRef.current = requestAnimationFrame(animate);
      } else {
        animRef.current = null;
      }
    };

    if (animRef.current) {
      cancelAnimationFrame(animRef.current);
    }
    animRef.current = requestAnimationFrame(animate);

    return () => {
      if (animRef.current) {
        cancelAnimationFrame(animRef.current);
      }
    };
  }, [activeIdx, aspect]);

  const handleMouseEnter = (idx: number) => {
    if (hoverTimer.current) {
      window.clearTimeout(hoverTimer.current);
    }
    hoverTimer.current = window.setTimeout(() => {
      setActiveIdx(idx);
    }, 40);
  };

  const handleClick = (idx: number) => {
    if (hoverTimer.current) {
      window.clearTimeout(hoverTimer.current);
    }
    setActiveIdx(idx);
  };

  const handleMouseLeave = () => {
    if (hoverTimer.current) {
      window.clearTimeout(hoverTimer.current);
    }
    hoverTimer.current = window.setTimeout(() => {
      setActiveIdx(null);
    }, 70);
  };

  const activeNode = activeIdx !== null ? NODES[activeIdx] : null;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1.6fr_1fr] gap-5 items-stretch mt-10">
      {/* Fixed size diagram card - full-bleed viewport filling the whole card */}
      <div
        ref={cardRef}
        className="shiny-card rounded-2xl p-0 flex items-center justify-center min-h-[380px] max-h-[380px] h-[380px] overflow-hidden relative select-none"
        onMouseLeave={handleMouseLeave}
      >
        <svg
          viewBox={`${viewBox.x.toFixed(2)} ${viewBox.y.toFixed(2)} ${viewBox.w.toFixed(2)} ${viewBox.h.toFixed(2)}`}
          className="w-full h-full block select-none pointer-events-auto"
          preserveAspectRatio="xMidYMid slice"
          role="img"
          aria-label="CacheBuddy architecture flow"
          textRendering="geometricPrecision"
          shapeRendering="geometricPrecision"
        >
          {/* Static connection lines */}
          {EDGES.map((e, idx) => (
            <React.Fragment key={`edge-${idx}`}>
              <path
                d={`M${e[0]} ${e[1]}L${e[2]} ${e[3]}`}
                className="stroke-white/20 fill-none"
                strokeWidth="1.5"
              />
              <path
                d={`M${e[0]} ${e[1]}L${e[2]} ${e[3]}`}
                className="stroke-white/60 fill-none fl-anim"
                strokeWidth="1.5"
              />
            </React.Fragment>
          ))}

          {/* Nodes */}
          {NODES.map((n, idx) => {
            const isAct = activeIdx === idx;

            return (
              <g
                key={n.id}
                tabIndex={0}
                onMouseEnter={() => handleMouseEnter(idx)}
                onFocus={() => handleMouseEnter(idx)}
                onClick={() => handleClick(idx)}
                className="cursor-pointer outline-none"
              >
                <rect
                  x={n.x}
                  y={n.y}
                  width="150"
                  height="56"
                  rx="10"
                  className={`transition-colors duration-200 ${isAct
                    ? 'fill-white stroke-white'
                    : 'fill-[#151518] stroke-white/20 hover:stroke-white/50'
                    }`}
                  strokeWidth="1"
                />
                <text
                  x={n.x + 14}
                  y={n.y + 24}
                  className={`text-xs font-semibold select-none pointer-events-none transition-colors duration-200 ${isAct ? 'fill-black' : 'fill-white'
                    }`}
                >
                  {n.a}
                </text>
                <text
                  x={n.x + 14}
                  y={n.y + 42}
                  className={`text-[10px] select-none pointer-events-none transition-colors duration-200 ${isAct ? 'fill-black/70' : 'fill-zinc-400'
                    }`}
                >
                  {n.b}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      {/* Fixed inspector details panel */}
      <div className="shiny-card rounded-2xl p-7 flex flex-col justify-between min-h-[380px] max-h-[380px] h-[380px] overflow-hidden">
        {activeNode ? (
          <div className="flex flex-col h-full justify-between">
            <div>
              <div className="text-[11px] font-mono tracking-wider uppercase text-zinc-400 mb-2">
                {String(activeIdx! + 1).padStart(2, '0')} · {activeNode.t}
              </div>
              <h3 className="text-xl sm:text-2xl font-bold tracking-tight text-white mb-2">
                {activeNode.h}
              </h3>
              <p className="text-sm text-zinc-300 leading-relaxed mb-4">
                {activeNode.p}
              </p>
            </div>
            <ul className="space-y-2 border-t border-white/[0.08] pt-4 mt-auto">
              {activeNode.l.map(([k, v]) => (
                <li key={k} className="flex justify-between text-xs text-zinc-400">
                  <span>{k}</span>
                  <b className="font-mono text-zinc-200">{v}</b>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <div className="flex flex-col justify-center h-full">
            <div className="text-[11px] font-mono tracking-wider uppercase text-zinc-400 mb-2">
              Interactive
            </div>
            <h3 className="text-xl font-bold text-white mb-2">Hover a stage</h3>
            <p className="text-sm text-zinc-400">
              Move across the diagram to zoom into a stage and read what it does and why it exists. Tap a stage on touch devices.
            </p>
          </div>
        )}
      </div>
    </div>
  );
};
