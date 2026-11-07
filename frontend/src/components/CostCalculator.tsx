import React, { useState } from 'react';

export const CostCalculator: React.FC = () => {
  const [replies, setReplies] = useState<number>(20000);
  const [hitRate, setHitRate] = useState<number>(75);

  const baseCredits = (replies * 120) / 370;
  const withCacheCredits = baseCredits * (1 - hitRate / 100);
  const creditsSaved = baseCredits - withCacheCredits;

  const fmt = (n: number) => Math.round(n).toLocaleString();

  return (
    <div className="shiny-card p-6 rounded-2xl flex flex-col gap-4">
      <h3 className="text-lg font-semibold tracking-tight text-white">Model your savings</h3>
      <p className="text-sm text-zinc-400">
        Every cached clause is a TTS call you never make. Drag the sliders. Figures are modeled at 120 characters per reply and the measured 370 characters per credit.
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 mt-1">
        <div>
          <div className="flex justify-between text-xs text-zinc-400 mb-2">
            <span>Replies per day</span>
            <span className="font-mono text-zinc-200">{fmt(replies)}</span>
          </div>
          <input
            type="range"
            min="1000"
            max="100000"
            step="1000"
            value={replies}
            onChange={(e) => setReplies(Number(e.target.value))}
            className="w-full accent-white cursor-pointer"
          />
        </div>

        <div>
          <div className="flex justify-between text-xs text-zinc-400 mb-2">
            <span>Cache hit rate</span>
            <span className="font-mono text-zinc-200">{hitRate}%</span>
          </div>
          <input
            type="range"
            min="0"
            max="95"
            step="5"
            value={hitRate}
            onChange={(e) => setHitRate(Number(e.target.value))}
            className="w-full accent-white cursor-pointer"
          />
        </div>
      </div>

      <div className="space-y-3 mt-2">
        <div>
          <div className="flex justify-between text-xs font-mono text-zinc-400 mb-1.5">
            <span>Without cache</span>
            <span>{fmt(baseCredits)} credits</span>
          </div>
          <div className="h-3 bg-zinc-800 rounded-full overflow-hidden">
            <div className="h-full bg-zinc-500 rounded-full w-full transition-all duration-300" />
          </div>
        </div>

        <div>
          <div className="flex justify-between text-xs font-mono text-zinc-400 mb-1.5">
            <span>With CacheBuddy</span>
            <span>{fmt(withCacheCredits)} credits</span>
          </div>
          <div className="h-3 bg-zinc-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-white rounded-full transition-all duration-300"
              style={{ width: `${Math.max(2, (1 - hitRate / 100) * 100)}%` }}
            />
          </div>
        </div>
      </div>

      <div className="mt-2 pt-2 border-t border-white/[0.08]">
        <div className="text-4xl sm:text-5xl font-bold tracking-tight text-white font-mono">
          {fmt(creditsSaved)}
        </div>
        <p className="text-xs text-zinc-400 mt-1">estimated credits saved per day</p>
      </div>
    </div>
  );
};

