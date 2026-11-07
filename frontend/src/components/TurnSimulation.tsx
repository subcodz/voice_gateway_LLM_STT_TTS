import React, { useState, useEffect } from 'react';

interface Step {
  stage: string;
  component: string;
  sub: string;
}

const STEPS: Step[] = [
  { stage: 'Speech', component: 'STT', sub: 'Gnani v3' },
  { stage: 'Route', component: 'Router', sub: 'rules + e5' },
  { stage: 'Reply', component: 'LLM layer', sub: 'cache first' },
  { stage: 'Audio', component: 'Clause cache', sub: 'L1 / L2' },
  { stage: 'Stream', component: 'TTS + tee', sub: 'timbre-v2.5' },
];

const QUERIES = [
  { q: 'What are the office hours?', route: 'cached_intent', speed: '38 ms · hit', chars: 0 },
  { q: 'How can I pay my bill online?', route: 'cached_intent', speed: '41 ms · hit', chars: 0 },
  { q: 'আমার বিলটা ভুল এসেছে', route: 'personalized', speed: 'live LLM · uncacheable', chars: 86 },
  { q: 'I will take this to the consumer forum', route: 'heavy_llm', speed: 'escalated', chars: 110 },
];

export const TurnSimulation: React.FC = () => {
  const [activeStep, setActiveStep] = useState<number>(0);
  const [queryIndex, setQueryIndex] = useState<number>(0);
  const [charsSent, setCharsSent] = useState<number>(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setActiveStep((prevStep) => {
        if (prevStep >= 4) {
          setQueryIndex((prevQ) => {
            const nextQ = (prevQ + 1) % QUERIES.length;
            setCharsSent((c) => c + QUERIES[nextQ].chars);
            return nextQ;
          });
          return 0;
        }
        return prevStep + 1;
      });
    }, 900);
    return () => clearInterval(timer);
  }, []);

  const curQ = QUERIES[queryIndex];

  return (
    <div className="shiny-card p-6 rounded-2xl max-w-[820px] mx-auto text-left shadow-2xl">
      <div className="flex justify-between items-center text-xs text-zinc-400 font-mono mb-4 pb-2 border-b border-white/[0.08]">
        <span className="flex items-center gap-2">
          Turns cached
        </span>
        <span className="text-zinc-300">cache-ON · {charsSent} chars sent</span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
        {STEPS.map((st, idx) => {
          const isOn = idx <= activeStep;
          return (
            <div
              key={st.stage}
              className={`p-3 rounded-xl border transition-all duration-300 ${isOn
                ? 'bg-zinc-900 border-white/20 text-white shadow-sm -translate-y-0.5'
                : 'bg-zinc-900/40 border-white/[0.06] text-zinc-500 opacity-60'
                }`}
            >
              <small className="block text-[11px] text-zinc-400">{st.stage}</small>
              <b className="text-xs sm:text-sm font-semibold">{st.component}</b>
              <span className="block text-[11px] font-mono text-zinc-400 mt-1">{st.sub}</span>
            </div>
          );
        })}
      </div>

      <div className="mt-4 p-3.5 rounded-xl bg-zinc-900/80 border border-white/[0.08] text-sm flex flex-wrap justify-between items-center gap-2">
        <span className="text-zinc-200">{curQ.q}</span>
        <em className="not-italic text-xs font-mono bg-white text-black px-2.5 py-1 rounded font-semibold">
          {curQ.route} · {curQ.speed}
        </em>
      </div>
    </div>
  );
};

