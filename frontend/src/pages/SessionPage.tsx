import React, { useState, useEffect, useRef } from 'react';
import { GuidedPrompt, TurnSummary, SessionSnapshot, ArmData } from '../types';
import { concat, fixWav, AudioQueuePlayer } from '../utils/audio';

const GUIDED: GuidedPrompt[] = [
  { label: '1  Bill payment', text: 'How can I pay my electricity bill online?', hint: 'Cold: nothing cached yet' },
  { label: '2  Office hours', text: 'What are the office hours?', hint: 'Different question' },
  { label: '3  Repeat of 1', text: 'how can i pay my electricity bill online', hint: 'Same query after normalization: exact hit' },
  { label: '4  Paraphrase of 1', text: 'What are the ways to pay the electricity bill online?', hint: 'Semantic hit if similarity clears threshold' },
  { label: '5  New question', text: 'What should I do about voltage fluctuation?', hint: 'Miss on LLM, partial clause reuse possible' },
];

const SOURCE_LABEL: Record<string, string> = {
  llm: 'LLM call',
  exact_hit: 'LLM cache: exact hit',
  semantic_hit: 'LLM cache: semantic hit',
  intent_cache: 'Intent cache',
  llm_uncacheable: 'LLM call (personal, uncacheable)',
  llm_failed: 'LLM failed, fallback reply',
};

const fmtMs = (v: number | null | undefined) => {
  if (v === null || v === undefined) return '--';
  return v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`;
};

const fmtNum = (v: number | null | undefined) => Number(v || 0).toLocaleString();

const createBlankArm = (): ArmData => ({
  chunks: {},
  clips: [],
  src: [],
  m: null,
  firstAudioClientMs: null,
});

export const SessionPage: React.FC<{ setModeBadge: (b: string) => void }> = ({ setModeBadge }) => {
  const [turns, setTurns] = useState<TurnSummary[]>([]);
  const [inputText, setInputText] = useState<string>('');
  const [busy, setBusy] = useState<boolean>(false);
  const [autoplay, setAutoplay] = useState<boolean>(true);
  const [snap, setSnap] = useState<SessionSnapshot | null>(null);
  const [notice, setNotice] = useState<string>('');
  const [usedGuided, setUsedGuided] = useState<Set<number>>(new Set());

  const wsRef = useRef<WebSocket | null>(null);
  const sessionIdRef = useRef<string>(
    typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : String(Date.now())
  );
  const playerRef = useRef<AudioQueuePlayer>(new AudioQueuePlayer());
  const pendingHdrRef = useRef<any>(null);
  const curTurnRef = useRef<TurnSummary | null>(null);

  // Initialize and connect WebSocket
  useEffect(() => {
    connectWs();
    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, []);

  const connectWs = () => {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(`${proto}//${window.location.host}/ws/session`);
    socket.binaryType = 'arraybuffer';

    socket.onopen = () => {
      setModeBadge('connecting…');
    };

    socket.onmessage = (ev) => {
      if (typeof ev.data !== 'string') {
        handleAudioBytes(new Uint8Array(ev.data));
        return;
      }

      try {
        const m = JSON.parse(ev.data);
        handleJsonMessage(m);
      } catch (err) {
        console.error('Failed to parse WebSocket JSON message', err);
      }
    };
    {/* 
    socket.onerror = () => {
      setModeBadge('offline');
      setNotice('Could not connect to WebSocket backend.');
      setBusy(false);
    };
    */}


    socket.onclose = () => {
      setModeBadge('disconnected');
      setBusy(false);
    };

    wsRef.current = socket;
  };

  const handleJsonMessage = (m: any) => {
    switch (m.type) {
      case 'ready':
        setModeBadge(m.mock ? 'mock APIs (zero credits)' : 'live Gnani');
        break;

      case 'turn_start': {
        const newTurn: TurnSummary = {
          turn: m.turn,
          text: m.text,
          lang: m.lang,
          reply: null,
          source: null,
          sim: 0,
          replyAt: null,
          replyReadyMs: 0,
          cached: createBlankArm(),
          uncached: createBlankArm(),
          skipped: false,
          summary: null,
        };
        curTurnRef.current = newTurn;
        setTurns((prev) => [...prev, newTurn]);
        playerRef.current.stop();
        break;
      }

      case 'reply': {
        if (!curTurnRef.current) return;
        curTurnRef.current.reply = m.text;
        curTurnRef.current.source = m.source;
        curTurnRef.current.sim = m.sim_score;
        curTurnRef.current.replyReadyMs = m.reply_ready_ms;
        curTurnRef.current.replyAt = performance.now();
        setTurns((prev) =>
          prev.map((t) => (t.turn === curTurnRef.current?.turn ? { ...curTurnRef.current } : t))
        );
        break;
      }

      case 'audio': {
        pendingHdrRef.current = m;
        break;
      }

      case 'clause_done': {
        if (!curTurnRef.current) return;
        const armKey = m.arm as 'cached' | 'uncached';
        const a = curTurnRef.current[armKey];
        const wav = fixWav(concat(a.chunks[m.clause] || []));
        a.clips[m.clause] = wav;
        a.src[m.clause] = m.source;
        delete a.chunks[m.clause];

        if (m.arm === 'cached' && autoplay) {
          playerRef.current.enqueue(wav);
        }

        setTurns((prev) =>
          prev.map((t) => (t.turn === curTurnRef.current?.turn ? { ...curTurnRef.current } : t))
        );
        break;
      }

      case 'arm_done': {
        if (!curTurnRef.current) return;
        const armKey = m.arm as 'cached' | 'uncached';
        curTurnRef.current[armKey].m = m.metrics;
        setTurns((prev) =>
          prev.map((t) => (t.turn === curTurnRef.current?.turn ? { ...curTurnRef.current } : t))
        );
        break;
      }

      case 'turn_done': {
        if (curTurnRef.current) {
          curTurnRef.current.summary = m.turn_summary;
        }
        setSnap(m.session);
        if (m.turn_summary?.compared === false) {
          setNotice('One audio path failed on this turn, so it is omitted from totals.');
        }
        finishTurn();
        break;
      }

      case 'cap': {
        setNotice(m.message);
        if (curTurnRef.current && !curTurnRef.current.reply) {
          setTurns((prev) => prev.slice(0, -1));
        }
        finishTurn();
        break;
      }

      case 'error': {
        setNotice(m.message);
        if (curTurnRef.current && !curTurnRef.current.reply) {
          curTurnRef.current.reply = 'No reply could be generated.';
          curTurnRef.current.source = '';
        }
        finishTurn();
        break;
      }

      default:
        break;
    }
  };

  const handleAudioBytes = (bytes: Uint8Array) => {
    if (!pendingHdrRef.current || !curTurnRef.current) return;
    const { arm, clause } = pendingHdrRef.current;
    pendingHdrRef.current = null;
    const a = curTurnRef.current[arm as 'cached' | 'uncached'];
    if (!a.chunks[clause]) {
      a.chunks[clause] = [];
    }
    a.chunks[clause].push(bytes);
    if (a.firstAudioClientMs === null && curTurnRef.current.replyAt) {
      a.firstAudioClientMs = performance.now() - curTurnRef.current.replyAt;
    }
  };

  const finishTurn = () => {
    if (curTurnRef.current && !curTurnRef.current.cached.m && !curTurnRef.current.uncached.m) {
      curTurnRef.current.skipped = true;
    }
    setBusy(false);
    setTurns((prev) =>
      prev.map((t) => (t.turn === curTurnRef.current?.turn ? { ...curTurnRef.current } : t))
    );
  };

  const sendTurn = (text: string) => {
    const clean = text.trim();
    if (!clean || busy) return;

    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      setNotice('Reconnecting to server…');
      connectWs();
      return;
    }

    setNotice('');
    setBusy(true);
    wsRef.current.send(
      JSON.stringify({
        type: 'turn',
        session_id: sessionIdRef.current,
        text: clean,
      })
    );
    setInputText('');
  };

  const resetSession = () => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: 'reset',
          session_id: sessionIdRef.current,
        })
      );
    }
    sessionIdRef.current =
      typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
    setTurns([]);
    curTurnRef.current = null;
    setSnap(null);
    pendingHdrRef.current = null;
    setUsedGuided(new Set());
    playerRef.current.stop();
    setNotice('');
    setBusy(false);
  };

  const handleReplay = (turnNum: number, arm: 'cached' | 'uncached') => {
    const t = turns.find((x) => x.turn === turnNum);
    if (t && t[arm].clips.length) {
      playerRef.current.replay(t[arm].clips);
    }
  };

  // Calculations for savings
  const saved = snap?.saved;
  const onArm = snap?.arms.cached;
  const offArm = snap?.arms.uncached;
  const tn = Math.max(1, onArm?.timed_turns || 0);
  const pct = (s: number, b: number) => (b > 0 ? ` (${Math.round((s / b) * 100)}%)` : '');
  const hitRate = onArm?.clauses ? `${Math.round((onArm.clause_hits / onArm.clauses) * 100)}%` : '--';

  const maxChars = Math.max(
    1,
    ...turns.map((t) => Math.max(t.cached.m?.tts_chars || 0, t.uncached.m?.tts_chars || 0))
  );

  return (
    <div className="flex flex-col flex-1 max-w-[1040px] mx-auto w-full px-4 sm:px-6 py-6 pb-28">
      {/* Intro Description */}
      <p className="text-xs sm:text-sm text-zinc-400 leading-relaxed mb-4">
        Each message makes <b className="text-zinc-200">one</b> LLM decision (cached or fresh). The{' '}
        <b className="text-zinc-200">same reply text</b> then goes down two audio paths: one with the TTS audio cache,
        one that synthesizes every clause. This session's cache starts empty, so turn 1 is always a cold miss.
      </p>

      {/* Notice Banner */}
      {notice && (
        <div className="mb-4 px-4 py-2.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-300 text-xs sm:text-sm flex items-center justify-between">
          <span>{notice}</span>
          <button onClick={() => setNotice('')} className="text-amber-400 hover:text-white">✕</button>
        </div>
      )}

      {/* Metrics Ribbon */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <div className="shiny-card p-4 rounded-xl">
          <span className="text-[11px] font-mono uppercase text-zinc-400 block mb-1">Characters Saved</span>
          <div className="flex items-baseline gap-1.5">
            <span className="text-2xl font-bold font-mono text-white">{saved ? fmtNum(saved.tts_chars) : '0'}</span>
            <span className="text-xs text-zinc-400">chars</span>
          </div>
          <span className="text-[11px] text-zinc-400 block mt-1">
            {saved && offArm?.tts_chars
              ? `${Math.round((saved.tts_chars / offArm.tts_chars) * 100)}% of what cache-off sent`
              : 'not sent to TTS'}
          </span>
        </div>

        <div className="shiny-card p-4 rounded-xl">
          <span className="text-[11px] font-mono uppercase text-zinc-400 block mb-1">Est. Credits Saved</span>
          <div className="flex items-baseline gap-1.5">
            <span className="text-2xl font-bold font-mono text-white">{saved ? saved.est_credits.toFixed(2) : '0'}</span>
            <span className="text-xs text-zinc-400">credits</span>
          </div>
          <span className="text-[11px] text-zinc-400 block mt-1">~370 chars/credit ratio</span>
        </div>

        <div className="shiny-card p-4 rounded-xl">
          <span className="text-[11px] font-mono uppercase text-zinc-400 block mb-1">TTS Calls Saved</span>
          <div className="flex items-baseline gap-1.5">
            <span className="text-2xl font-bold font-mono text-white">{saved ? fmtNum(saved.tts_calls) : '0'}</span>
            <span className="text-xs text-zinc-400">calls</span>
          </div>
          <span className="text-[11px] text-zinc-400 block mt-1">clauses served from cache</span>
        </div>

        <div className="shiny-card p-4 rounded-xl">
          <span className="text-[11px] font-mono uppercase text-zinc-400 block mb-1">Wait Saved</span>
          <div className="flex items-baseline gap-1.5">
            <span className="text-2xl font-bold font-mono text-white">
              {saved ? fmtMs(saved.first_playable_ms) : '0 ms'}
            </span>
            <span className="text-xs text-zinc-400">to first sound</span>
          </div>
          <span className="text-[11px] text-zinc-400 block mt-1">cumulative over session</span>
        </div>
      </div>

      {/* Conversation Thread */}
      <div className="shiny-card p-5 rounded-2xl min-h-[120px] mb-6 flex flex-col gap-4">
        {!turns.length ? (
          <span className="text-zinc-500 text-sm">Pick a guided prompt below, or type your own to start.</span>
        ) : (
          turns.map((t) => {
            const hit =
              t.source === 'exact_hit' || t.source === 'semantic_hit' || t.source === 'intent_cache';
            const label = t.source ? SOURCE_LABEL[t.source] || t.source : '';
            const sim = t.source === 'semantic_hit' ? ` ${(t.sim * 100).toFixed(1)}%` : '';

            return (
              <div key={t.turn} className="flex flex-col gap-2">
                {/* User Bubble */}
                <div className="self-end bg-zinc-800 border border-white/10 text-zinc-200 px-3.5 py-2 rounded-xl text-sm max-w-[85%]">
                  {t.text}
                </div>

                {/* Agent Bubble */}
                <div className="self-start bg-zinc-900 border border-white/[0.08] text-white px-3.5 py-2 rounded-xl text-sm max-w-[85%] leading-relaxed">
                  {t.reply ? t.reply : 'Thinking…'}
                </div>

                {/* Timing Badge */}
                {t.reply && (
                  <div className="self-start flex flex-wrap items-center gap-2 text-[11px] font-mono text-zinc-400 pl-1">
                    <span
                      className={`px-2 py-0.5 rounded border text-[10px] font-medium ${hit
                          ? 'bg-white text-black border-white'
                          : 'bg-zinc-800 text-zinc-300 border-white/10'
                        }`}
                    >
                      {label}
                      {sim}
                    </span>
                    <span>reply ready in {fmtMs(t.replyReadyMs)}</span>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Dual Arm Comparison Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        {/* Arm Cached */}
        <div className="shiny-card p-5 rounded-2xl flex flex-col gap-3">
          <div>
            <h3 className="text-base font-semibold text-white">TTS cache ON</h3>
            <span className="text-xs text-zinc-400">Clause lookup, singleflight tee on miss</span>
          </div>

          <div className="space-y-3">
            {!turns.length ? (
              <div className="text-xs text-zinc-500 py-3">No turns yet.</div>
            ) : (
              [...turns].reverse().map((t) => {
                const a = t.cached;
                const m = a.m;
                const n = m ? m.clauses : a.src.length;
                return (
                  <div key={`cached-${t.turn}`} className="p-3.5 rounded-xl bg-zinc-900 border border-white/[0.08] flex flex-col gap-2.5">
                    <div className="flex justify-between items-center text-xs text-zinc-400 uppercase font-mono font-semibold">
                      <span>Turn {t.turn}</span>
                      {a.clips.some(Boolean) && (
                        <button
                          onClick={() => handleReplay(t.turn, 'cached')}
                          className="px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-sans normal-case border border-white/10"
                        >
                          Play
                        </button>
                      )}
                    </div>

                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                      <div>
                        <span className="text-[10px] uppercase text-zinc-400 block font-mono">First sound</span>
                        <b className="font-mono text-white">{m ? fmtMs(m.first_playable_ms) : '…'}</b>
                      </div>
                      <div>
                        <span className="text-[10px] uppercase text-zinc-400 block font-mono">Full audio</span>
                        <b className="font-mono text-white">{m ? fmtMs(m.total_ms) : '…'}</b>
                      </div>
                      <div>
                        <span className="text-[10px] uppercase text-zinc-400 block font-mono">TTS chars</span>
                        <b className="font-mono text-white">{m ? fmtNum(m.tts_chars) : '…'}</b>
                      </div>
                      <div>
                        <span className="text-[10px] uppercase text-zinc-400 block font-mono">TTS calls</span>
                        <b className="font-mono text-white">{m ? m.tts_calls : '…'}</b>
                      </div>
                    </div>

                    {/* Chips */}
                    <div className="flex flex-wrap gap-1.5 mt-1">
                      {Array.from({ length: Math.max(n, a.src.length) }).map((_, i) => {
                        const s = a.src[i];
                        const isHit = s === 'hit';
                        return (
                          <span
                            key={i}
                            className={`text-[10px] font-mono px-2 py-0.5 rounded border ${isHit
                                ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                                : 'bg-zinc-800 text-zinc-400 border-white/10'
                              }`}
                          >
                            Clause {i + 1}: {s ? s.toUpperCase() : '…'}
                          </span>
                        );
                      })}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Arm Uncached */}
        <div className="shiny-card p-5 rounded-2xl flex flex-col gap-3">
          <div>
            <h3 className="text-base font-semibold text-white">TTS cache OFF</h3>
            <span className="text-xs text-zinc-400">Every clause synthesized, zero cache</span>
          </div>

          <div className="space-y-3">
            {!turns.length ? (
              <div className="text-xs text-zinc-500 py-3">No turns yet.</div>
            ) : (
              [...turns].reverse().map((t) => {
                const a = t.uncached;
                const m = a.m;
                const n = m ? m.clauses : a.src.length;
                return (
                  <div key={`uncached-${t.turn}`} className="p-3.5 rounded-xl bg-zinc-900 border border-white/[0.08] flex flex-col gap-2.5">
                    <div className="flex justify-between items-center text-xs text-zinc-400 uppercase font-mono font-semibold">
                      <span>Turn {t.turn}</span>
                      {a.clips.some(Boolean) && (
                        <button
                          onClick={() => handleReplay(t.turn, 'uncached')}
                          className="px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-sans normal-case border border-white/10"
                        >
                          Play
                        </button>
                      )}
                    </div>

                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                      <div>
                        <span className="text-[10px] uppercase text-zinc-400 block font-mono">First sound</span>
                        <b className="font-mono text-white">{m ? fmtMs(m.first_playable_ms) : '…'}</b>
                      </div>
                      <div>
                        <span className="text-[10px] uppercase text-zinc-400 block font-mono">Full audio</span>
                        <b className="font-mono text-white">{m ? fmtMs(m.total_ms) : '…'}</b>
                      </div>
                      <div>
                        <span className="text-[10px] uppercase text-zinc-400 block font-mono">TTS chars</span>
                        <b className="font-mono text-white">{m ? fmtNum(m.tts_chars) : '…'}</b>
                      </div>
                      <div>
                        <span className="text-[10px] uppercase text-zinc-400 block font-mono">TTS calls</span>
                        <b className="font-mono text-white">{m ? m.tts_calls : '…'}</b>
                      </div>
                    </div>

                    {/* Chips */}
                    <div className="flex flex-wrap gap-1.5 mt-1">
                      {Array.from({ length: Math.max(n, a.src.length) }).map((_, i) => {
                        const s = a.src[i];
                        return (
                          <span
                            key={i}
                            className="text-[10px] font-mono px-2 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-white/10"
                          >
                            Clause {i + 1}: {s ? s.toUpperCase() : 'SYNTH'}
                          </span>
                        );
                      })}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>

      {/* Savings Table & Comparative Bar Chart */}
      {snap && onArm && offArm && saved && saved.compared_turns > 0 && (
        <div className="shiny-card p-6 rounded-2xl mb-6">
          <h3 className="text-lg font-semibold text-white mb-4">
            Savings so far ({onArm.turns} turn{onArm.turns === 1 ? '' : 's'})
          </h3>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-white/10 text-zinc-400 font-mono uppercase text-[11px]">
                  <th className="py-2.5 pr-4">Metric</th>
                  <th className="py-2.5 px-4">Cache ON</th>
                  <th className="py-2.5 px-4">Cache OFF</th>
                  <th className="py-2.5 pl-4 text-emerald-400">Saved</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.06] text-zinc-200">
                <tr>
                  <td className="py-2.5 pr-4 font-medium text-white">Characters sent to TTS</td>
                  <td className="py-2.5 px-4 font-mono">{fmtNum(onArm.tts_chars)}</td>
                  <td className="py-2.5 px-4 font-mono">{fmtNum(offArm.tts_chars)}</td>
                  <td className="py-2.5 pl-4 font-mono text-emerald-400 font-semibold">
                    {fmtNum(saved.tts_chars)} {pct(saved.tts_chars, offArm.tts_chars)}
                  </td>
                </tr>
                <tr>
                  <td className="py-2.5 pr-4 font-medium text-white">Est. credits</td>
                  <td className="py-2.5 px-4 font-mono">{onArm.est_credits.toFixed(2)}</td>
                  <td className="py-2.5 px-4 font-mono">{offArm.est_credits.toFixed(2)}</td>
                  <td className="py-2.5 pl-4 font-mono text-emerald-400 font-semibold">
                    {saved.est_credits.toFixed(2)}
                  </td>
                </tr>
                <tr>
                  <td className="py-2.5 pr-4 font-medium text-white">TTS calls</td>
                  <td className="py-2.5 px-4 font-mono">{onArm.tts_calls}</td>
                  <td className="py-2.5 px-4 font-mono">{offArm.tts_calls}</td>
                  <td className="py-2.5 pl-4 font-mono text-emerald-400 font-semibold">
                    {saved.tts_calls} {pct(saved.tts_calls, offArm.tts_calls)}
                  </td>
                </tr>
                <tr>
                  <td className="py-2.5 pr-4 font-medium text-white">Avg time to first sound (hit turns only)</td>
                  <td className="py-2.5 px-4 font-mono">
                    {onArm.timed_turns ? fmtMs(onArm.first_playable_ms / tn) : '--'}
                  </td>
                  <td className="py-2.5 px-4 font-mono">
                    {offArm.timed_turns ? fmtMs(offArm.first_playable_ms / tn) : '--'}
                  </td>
                  <td className="py-2.5 pl-4 font-mono text-emerald-400 font-semibold">
                    {onArm.timed_turns ? fmtMs(saved.first_playable_ms / tn) : '--'}
                  </td>
                </tr>
                <tr>
                  <td className="py-2.5 pr-4 font-medium text-white">Avg time to full audio (hit turns only)</td>
                  <td className="py-2.5 px-4 font-mono">
                    {onArm.timed_turns ? fmtMs(onArm.total_ms / tn) : '--'}
                  </td>
                  <td className="py-2.5 px-4 font-mono">
                    {offArm.timed_turns ? fmtMs(offArm.total_ms / tn) : '--'}
                  </td>
                  <td className="py-2.5 pl-4 font-mono text-emerald-400 font-semibold">
                    {onArm.timed_turns ? fmtMs(saved.total_ms / tn) : '--'}
                  </td>
                </tr>
                <tr>
                  <td className="py-2.5 pr-4 font-medium text-white">Audio clause hit rate</td>
                  <td className="py-2.5 px-4 font-mono font-semibold text-emerald-400">{hitRate}</td>
                  <td className="py-2.5 px-4 font-mono">0%</td>
                  <td className="py-2.5 pl-4 font-mono">--</td>
                </tr>
                <tr>
                  <td className="py-2.5 pr-4 font-medium text-white">LLM layer</td>
                  <td className="py-2.5 px-4 font-mono">
                    {snap.llm.calls} call{snap.llm.calls === 1 ? '' : 's'}
                  </td>
                  <td className="py-2.5 px-4 font-mono text-zinc-400">same text feeds both</td>
                  <td className="py-2.5 pl-4 font-mono text-zinc-300">
                    {snap.llm.exact_hits} exact · {snap.llm.semantic_hits} semantic · {snap.llm.intent_hits} intent
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* Bar pairs */}
          <div className="mt-6 space-y-2 border-t border-white/[0.08] pt-4">
            <span className="text-xs font-semibold text-zinc-400 block mb-2">Turn by Turn Comparison</span>
            {turns
              .filter((t) => t.cached.m && t.uncached.m)
              .map((t) => {
                const onW = ((t.cached.m?.tts_chars || 0) / maxChars) * 100;
                const offW = ((t.uncached.m?.tts_chars || 0) / maxChars) * 100;
                return (
                  <div key={`bar-${t.turn}`} className="flex items-center gap-3 text-xs font-mono">
                    <span className="w-16 text-zinc-400">Turn {t.turn}</span>
                    <div className="flex-1 space-y-1">
                      <div className="h-2 rounded-full bg-white transition-all duration-300" style={{ width: `${onW}%` }} title={`cache ON: ${t.cached.m?.tts_chars} chars`} />
                      <div className="h-2 rounded-full bg-zinc-600 transition-all duration-300" style={{ width: `${offW}%` }} title={`cache OFF: ${t.uncached.m?.tts_chars} chars`} />
                    </div>
                  </div>
                );
              })}
            <div className="flex items-center gap-6 text-[11px] text-zinc-400 pt-3">
              <span className="flex items-center gap-2">
                <i className="w-2.5 h-2.5 rounded-full bg-white inline-block" />
                cache ON chars
              </span>
              <span className="flex items-center gap-2">
                <i className="w-2.5 h-2.5 rounded-full bg-zinc-600 inline-block" />
                cache OFF chars
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Floating Bottom Interaction Dock */}
      <footer className="fixed bottom-0 inset-x-0 bg-[#08080a]/90 backdrop-blur-md border-t border-white/10 z-40 py-3 shadow-2xl">
        <div className="max-w-[1040px] mx-auto px-4 sm:px-6 flex flex-col gap-2.5">
          {/* Guided prompt chips */}
          <div className="flex items-center gap-2 overflow-x-auto pb-1 no-scrollbar">
            <span className="text-[11px] font-mono uppercase tracking-wider text-zinc-400 whitespace-nowrap">
              Guided path:
            </span>
            {GUIDED.map((g, idx) => {
              const isUsed = usedGuided.has(idx);
              return (
                <button
                  key={idx}
                  disabled={busy}
                  onClick={() => {
                    setUsedGuided((s) => new Set([...s, idx]));
                    sendTurn(g.text);
                  }}
                  title={g.hint}
                  className={`text-xs px-3 py-1.5 rounded-lg border transition-all whitespace-nowrap ${isUsed
                      ? 'bg-zinc-900 border-white/[0.08] text-zinc-500 opacity-60'
                      : 'bg-zinc-800/80 hover:bg-zinc-700 border-white/10 text-zinc-200'
                    }`}
                >
                  {g.label}
                </button>
              );
            })}
          </div>

          {/* Main Input Dock Row */}
          <div className="flex items-center gap-3">
            <input
              type="text"
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') sendTurn(inputText);
              }}
              placeholder="Type a message (e.g. How can I pay my bill?)"
              className="flex-1 bg-zinc-900/90 border border-white/10 text-white placeholder-zinc-500 text-sm px-4 py-2.5 rounded-xl outline-none focus:border-white/30 transition-colors"
            />

            <label className="hidden sm:flex items-center gap-2 text-xs text-zinc-400 cursor-pointer select-none whitespace-nowrap">
              <input
                type="checkbox"
                checked={autoplay}
                onChange={(e) => setAutoplay(e.target.checked)}
                className="accent-white cursor-pointer"
              />
              Play audio
            </label>

            <button
              onClick={resetSession}
              title="Start over with empty cache"
              className="text-xs px-3.5 py-2.5 rounded-xl border border-white/10 bg-zinc-800/80 hover:bg-zinc-700 text-zinc-300 transition-colors whitespace-nowrap"
            >
              Reset
            </button>

            <button
              onClick={() => sendTurn(inputText)}
              disabled={busy || !inputText.trim()}
              className="text-xs sm:text-sm font-semibold px-5 py-2.5 rounded-xl bg-white text-black hover:bg-zinc-200 disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-md flex items-center gap-1.5 whitespace-nowrap"
            >
              <span>Send</span>
              <span>→</span>
            </button>
          </div>
        </div>
      </footer>
    </div>
  );
};

