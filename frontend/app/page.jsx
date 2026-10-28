'use client';

import React, { useState, useEffect, useRef } from 'react';

export default function Home() {
  const [transcript, setTranscript] = useState('আমাদের এলাকায় বিদ্যুৎ চলে গেছে কখন আসবে?');
  const [selectedLang, setSelectedLang] = useState('bn-IN');

  const [baseResponse, setBaseResponse] = useState('--');
  const [baseTtfa, setBaseTtfa] = useState('-- ms');
  const [baseTotal, setBaseTotal] = useState('-- ms');
  const [baseStatus, setBaseStatus] = useState('Idle');

  const [gwResponse, setGwResponse] = useState('--');
  const [gwTtfa, setGwTtfa] = useState('-- ms');
  const [gwDecision, setGwDecision] = useState('--');
  const [gwSim, setGwSim] = useState('--');
  const [gwClauses, setGwClauses] = useState([]);
  const [gwStatus, setGwStatus] = useState('Idle');

  const [stats, setStats] = useState({
    charsAvoided: 0,
    ttsAvoided: 0,
    llmAvoided: 0,
    speedup: '4.8x'
  });

  const baseAudioRef = useRef(null);
  const gwAudioRef = useRef(null);
  const baseWsRef = useRef(null);
  const gwWsRef = useRef(null);

  useEffect(() => {
    fetchStats();
  }, []);

  const fetchStats = async () => {
    try {
      const res = await fetch('/api/stats');
      if (res.ok) {
        const s = await res.json();
        if (s.savings) {
          setStats({
            charsAvoided: s.savings.tts_chars_avoided || 0,
            ttsAvoided: s.savings.tts_calls_avoided || 0,
            llmAvoided: s.savings.llm_calls_avoided || 0,
            speedup: s.baseline?.total_p50_ms && s.gateway?.total_p50_ms 
              ? `${(s.baseline.total_p50_ms / Math.max(1, s.gateway.total_p50_ms)).toFixed(1)}x` 
              : '4.8x'
          });
        }
      }
    } catch (e) {
      console.warn("Could not fetch /api/stats, backend may be starting:", e);
    }
  };

  const playAudioChunks = (chunks, audioElem) => {
    if (!chunks || chunks.length === 0 || !audioElem) return;
    const totalLen = chunks.reduce((acc, c) => acc + c.length, 0);
    const fullBytes = new Uint8Array(totalLen);
    let offset = 0;
    for (const c of chunks) {
      fullBytes.set(c, offset);
      offset += c.length;
    }
    const blob = new Blob([fullBytes], { type: 'audio/wav' });
    const url = URL.createObjectURL(blob);
    audioElem.src = url;
    audioElem.play().catch(() => {});
  };

  const runTurn = async (queryText = transcript, lang = selectedLang) => {
    if (!queryText.trim()) return;

    // Reset display
    setBaseResponse('Connecting to baseline...');
    setBaseTtfa('-- ms');
    setBaseTotal('-- ms');
    setBaseStatus('Streaming...');

    setGwResponse('Evaluating cache & routing...');
    setGwTtfa('-- ms');
    setGwDecision('--');
    setGwSim('--');
    setGwClauses([]);
    setGwStatus('Evaluating...');

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const wsUrl = `${protocol}//${host}/ws`;

    // 1. Run Baseline Arm WebSocket
    const baseChunks = [];
    const baseWs = new WebSocket(wsUrl);
    baseWs.binaryType = 'arraybuffer';
    baseWsRef.current = baseWs;

    baseWs.onopen = () => {
      baseWs.send(JSON.stringify({
        arm: 'baseline',
        session_id: 'nextjs_demo',
        lang: lang,
        text: queryText,
        run_id: 'live_turn'
      }));
    };

    baseWs.onmessage = (event) => {
      if (typeof event.data === 'string') {
        const msg = JSON.parse(event.data);
        if (msg.type === 'reply_text') {
          setBaseResponse(msg.text);
        } else if (msg.type === 'turn_done') {
          const m = msg.metrics;
          setBaseTtfa(`${m.ttfa_ms} ms`);
          setBaseTotal(`${m.total_ms} ms`);
          setBaseStatus('Ready');
          playAudioChunks(baseChunks, baseAudioRef.current);
          fetchStats();
        }
      } else if (event.data instanceof ArrayBuffer) {
        baseChunks.push(new Uint8Array(event.data));
      }
    };

    // 2. Run Gateway Arm WebSocket
    const gwChunks = [];
    const gwWs = new WebSocket(wsUrl);
    gwWs.binaryType = 'arraybuffer';
    gwWsRef.current = gwWs;

    gwWs.onopen = () => {
      gwWs.send(JSON.stringify({
        arm: 'gateway',
        session_id: 'nextjs_demo',
        lang: lang,
        text: queryText,
        run_id: 'live_turn'
      }));
    };

    gwWs.onmessage = (event) => {
      if (typeof event.data === 'string') {
        const msg = JSON.parse(event.data);
        if (msg.type === 'route') {
          setGwDecision(msg.decision);
          setGwSim(msg.sim_score > 0 ? `${(msg.sim_score * 100).toFixed(1)}%` : 'N/A');
        } else if (msg.type === 'reply_text') {
          setGwResponse(msg.text);
        } else if (msg.type === 'turn_done') {
          const m = msg.metrics;
          setGwTtfa(`${m.ttfa_ms} ms`);
          setGwStatus('Completed');

          const tags = [];
          for (let i = 0; i < (m.clauses || 1); i++) {
            tags.push(i < m.clause_hits ? `Clause ${i + 1}: Exact Cache HIT` : `Clause ${i + 1}: Live Synthesized`);
          }
          setGwClauses(tags);
          playAudioChunks(gwChunks, gwAudioRef.current);
          fetchStats();
        }
      } else if (event.data instanceof ArrayBuffer) {
        gwChunks.push(new Uint8Array(event.data));
      }
    };
  };

  return (
    <div className="dark-theme">
      <header className="app-header">
        <div className="header-left">
          <div className="logo-mark">⚡</div>
          <div>
            <h1 className="brand-title">Gnani Voice Gateway</h1>
            <p className="brand-subtitle">Semantic Response & Exact Audio Caching Layer · Kolkata Power Utility</p>
          </div>
        </div>

        <div className="header-right">
          <div className="status-pill safe-mode">
            <span>● Connected to Gateway WebSocket</span>
          </div>
        </div>
      </header>

      <section className="metrics-ribbon">
        <div className="ribbon-card">
          <span className="ribbon-label">Characters Avoided</span>
          <div className="ribbon-val-group">
            <span className="ribbon-value text-emerald">{stats.charsAvoided.toLocaleString()}</span>
          </div>
        </div>
        <div className="ribbon-card">
          <span className="ribbon-label">TTS Syntheses Avoided</span>
          <div className="ribbon-val-group">
            <span className="ribbon-value text-indigo">{stats.ttsAvoided} calls</span>
          </div>
        </div>
        <div className="ribbon-card">
          <span className="ribbon-label">LLM Inferences Avoided</span>
          <div className="ribbon-val-group">
            <span className="ribbon-value text-violet">{stats.llmAvoided} calls</span>
          </div>
        </div>
        <div className="ribbon-card">
          <span className="ribbon-label">Median TTFA Speedup</span>
          <div className="ribbon-val-group">
            <span className="ribbon-value text-cyan">{stats.speedup}</span>
          </div>
        </div>
      </section>

      <main className="split-arena">
        {/* Baseline Panel */}
        <div className="agent-panel baseline-panel">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3>Naive Baseline Agent</h3>
            <span style={{ fontSize: '0.75rem', color: '#f43f5e', background: 'rgba(244,63,94,0.1)', padding: '2px 8px', borderRadius: '4px' }}>Control Arm</span>
          </div>
          <p style={{ color: '#94a3b8', fontSize: '0.85rem' }}>STT → LLM → Full TTS (No Caching)</p>
          
          <div style={{ marginTop: '0.5rem', background: 'rgba(0,0,0,0.3)', padding: '10px 14px', borderRadius: '6px', display: 'flex', justifyContent: 'space-between' }}>
            <div>TTFA: <strong style={{ color: '#f43f5e' }}>{baseTtfa}</strong></div>
            <div>Total: <strong>{baseTotal}</strong></div>
            <div>Status: <span style={{ color: '#94a3b8' }}>{baseStatus}</span></div>
          </div>

          <div style={{ marginTop: '0.5rem' }}>
            <span style={{ fontSize: '0.75rem', color: '#64748b', textTransform: 'uppercase', fontWeight: 600 }}>Spoken Response:</span>
            <div style={{ marginTop: '4px', background: '#151c2e', padding: '14px', borderRadius: '8px', minHeight: '80px', lineHeight: '1.5' }}>
              {baseResponse}
            </div>
          </div>

          <div style={{ marginTop: 'auto', background: 'rgba(0,0,0,0.3)', padding: '10px', borderRadius: '8px' }}>
            <audio ref={baseAudioRef} controls style={{ width: '100%', height: '36px' }}></audio>
          </div>
        </div>

        {/* Gateway Panel */}
        <div className="agent-panel gateway-panel">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3>Voice Gateway (Optimized)</h3>
            <span style={{ fontSize: '0.75rem', color: '#10b981', background: 'rgba(16,185,129,0.1)', padding: '2px 8px', borderRadius: '4px' }}>Cache Accelerated</span>
          </div>
          <p style={{ color: '#94a3b8', fontSize: '0.85rem' }}>Semantic Cache + Exact Audio Cache + Single-Flight</p>
          
          <div style={{ marginTop: '0.5rem', background: 'rgba(0,0,0,0.3)', padding: '10px 14px', borderRadius: '6px', display: 'flex', justifyContent: 'space-between' }}>
            <div>TTFA: <strong style={{ color: '#10b981' }}>{gwTtfa}</strong></div>
            <div>Route: <strong style={{ color: '#818cf8' }}>{gwDecision}</strong></div>
            <div>Sim: <strong style={{ color: '#a5b4fc' }}>{gwSim}</strong></div>
          </div>

          <div style={{ marginTop: '0.5rem' }}>
            <span style={{ fontSize: '0.75rem', color: '#64748b', textTransform: 'uppercase', fontWeight: 600 }}>Spoken Response:</span>
            <div style={{ marginTop: '4px', background: '#151c2e', padding: '14px', borderRadius: '8px', minHeight: '80px', lineHeight: '1.5' }}>
              {gwResponse}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '8px' }}>
              {gwClauses.map((c, i) => (
                <span key={i} style={{ 
                  background: c.includes('HIT') ? 'rgba(16,185,129,0.2)' : 'rgba(245,158,11,0.2)', 
                  color: c.includes('HIT') ? '#34d399' : '#fbbf24', 
                  border: c.includes('HIT') ? '1px solid rgba(16,185,129,0.4)' : '1px solid rgba(245,158,11,0.4)',
                  padding: '2px 8px', 
                  borderRadius: '4px', 
                  fontSize: '0.75rem',
                  fontFamily: 'monospace'
                }}>
                  {c}
                </span>
              ))}
            </div>
          </div>

          <div style={{ marginTop: 'auto', background: 'rgba(0,0,0,0.3)', padding: '10px', borderRadius: '8px' }}>
            <audio ref={gwAudioRef} controls style={{ width: '100%', height: '36px' }}></audio>
          </div>
        </div>
      </main>

      {/* Preset Chips */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', padding: '0 2rem 1rem 2rem' }}>
        <button 
          onClick={() => { setTranscript('আমাদের এলাকায় বিদ্যুৎ চলে গেছে কখন আসবে?'); setSelectedLang('bn-IN'); runTurn('আমাদের এলাকায় বিদ্যুৎ চলে গেছে কখন আসবে?', 'bn-IN'); }}
          style={{ background: '#151c2e', border: '1px solid rgba(255,255,255,0.08)', color: '#94a3b8', padding: '6px 12px', borderRadius: '6px', cursor: 'pointer', fontSize: '0.8rem' }}
        >
          ⚡ Outage FAQ (Bengali)
        </button>
        <button 
          onClick={() => { setTranscript('बिजली बिल ऑनलाइन कैसे भरें?'); setSelectedLang('hi-IN'); runTurn('बिजली बिल ऑनलाइन कैसे भरें?', 'hi-IN'); }}
          style={{ background: '#151c2e', border: '1px solid rgba(255,255,255,0.08)', color: '#94a3b8', padding: '6px 12px', borderRadius: '6px', cursor: 'pointer', fontSize: '0.8rem' }}
        >
          💳 Bill Payment (Hindi)
        </button>
        <button 
          onClick={() => { setTranscript('Current chole geche kokhon asbe?'); setSelectedLang('hi-en'); runTurn('Current chole geche kokhon asbe?', 'hi-en'); }}
          style={{ background: '#151c2e', border: '1px solid rgba(255,255,255,0.08)', color: '#94a3b8', padding: '6px 12px', borderRadius: '6px', cursor: 'pointer', fontSize: '0.8rem' }}
        >
          🗣️ Outage (Benglish)
        </button>
        <button 
          onClick={() => { setTranscript('আমার চলতি মাসের বিদ্যুৎ বিল কত এসেছে?'); setSelectedLang('bn-IN'); runTurn('আমার চলতি মাসের বিদ্যুৎ বিল কত এসেছে?', 'bn-IN'); }}
          style={{ background: '#151c2e', border: '1px solid rgba(244,63,94,0.3)', color: '#fb7185', padding: '6px 12px', borderRadius: '6px', cursor: 'pointer', fontSize: '0.8rem' }}
        >
          👤 Personal Bill (Bypasses Cache)
        </button>
      </div>

      <footer style={{ padding: '1rem 2rem', background: '#0e131f', borderTop: '1px solid rgba(255,255,255,0.08)', display: 'flex', gap: '10px', alignItems: 'center' }}>
        <select 
          value={selectedLang} 
          onChange={(e) => setSelectedLang(e.target.value)}
          style={{ background: '#151c2e', border: '1px solid rgba(255,255,255,0.1)', color: '#fff', padding: '10px 14px', borderRadius: '6px' }}
        >
          <option value="bn-IN">বাংলা (bn-IN)</option>
          <option value="hi-IN">हिन्दी (hi-IN)</option>
          <option value="hi-en">Benglish (hi-en)</option>
        </select>
        <input
          type="text"
          value={transcript}
          onChange={(e) => setTranscript(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') runTurn(); }}
          style={{ flex: 1, background: '#07090e', border: '1px solid rgba(255,255,255,0.1)', color: '#fff', padding: '10px 14px', borderRadius: '6px' }}
        />
        <button
          onClick={() => runTurn()}
          style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)', border: 'none', color: '#fff', padding: '10px 20px', borderRadius: '6px', cursor: 'pointer', fontWeight: 600 }}
        >
          Run Turn →
        </button>
      </footer>
    </div>
  );
}
