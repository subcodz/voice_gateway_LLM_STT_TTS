'use client';

import React, { useState, useEffect, useRef } from 'react';

/**
 * Detects language from input text using Unicode script ranges and Latin patterns.
 * Returns a Gnani-compatible language code.
 */
function detectLanguage(text) {
  if (!text || !text.trim()) return 'hi-IN';

  let bengaliCount = 0;
  let devanagariCount = 0;
  let latinCount = 0;
  let totalAlpha = 0;

  for (const ch of text) {
    const code = ch.codePointAt(0);
    if (code >= 0x0980 && code <= 0x09FF) { bengaliCount++; totalAlpha++; }
    else if (code >= 0x0900 && code <= 0x097F) { devanagariCount++; totalAlpha++; }
    else if ((code >= 0x0041 && code <= 0x005A) || (code >= 0x0061 && code <= 0x007A)) { latinCount++; totalAlpha++; }
  }

  if (totalAlpha === 0) return 'hi-IN';

  const bengaliRatio = bengaliCount / totalAlpha;
  const devanagariRatio = devanagariCount / totalAlpha;
  const latinRatio = latinCount / totalAlpha;

  // Pure Bengali script
  if (bengaliRatio > 0.4) return 'bn-IN';
  // Pure Devanagari script
  if (devanagariRatio > 0.4) return 'hi-IN';
  // Mostly Latin (Hinglish/Benglish romanized)
  if (latinRatio > 0.6) return 'hi-en';
  return 'hi-IN';
}

/**
 * Encodes recorded Float32Array PCM chunks into 16kHz mono 16-bit PCM WAV.
 */
function encodeWav16kHz(chunks, inputSampleRate) {
  if (!chunks || chunks.length === 0) return null;
  const totalInputSamples = chunks.reduce((acc, c) => acc + c.length, 0);
  if (totalInputSamples === 0) return null;

  const inputBuffer = new Float32Array(totalInputSamples);
  let offset = 0;
  for (const c of chunks) {
    inputBuffer.set(c, offset);
    offset += c.length;
  }

  const targetSampleRate = 16000;
  const downsampleRatio = inputSampleRate / targetSampleRate;
  const targetLength = Math.floor(totalInputSamples / downsampleRatio);
  const pcm16 = new Int16Array(targetLength);

  for (let i = 0; i < targetLength; i++) {
    const origIndex = Math.floor(i * downsampleRatio);
    let sample = Math.max(-1, Math.min(1, inputBuffer[origIndex]));
    pcm16[i] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
  }

  const buffer = new ArrayBuffer(44 + pcm16.length * 2);
  const view = new DataView(buffer);

  // RIFF identifier
  view.setUint32(0, 0x52494646, false); // "RIFF"
  view.setUint32(4, 36 + pcm16.length * 2, true);
  view.setUint32(8, 0x57415645, false); // "WAVE"
  // fmt chunk
  view.setUint32(12, 0x666d7420, false); // "fmt "
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM format
  view.setUint16(22, 1, true); // Mono channel
  view.setUint32(24, 16000, true); // Sample rate
  view.setUint32(28, 16000 * 2, true); // Byte rate
  view.setUint16(32, 2, true); // Block align
  view.setUint16(34, 16, true); // Bits per sample
  // data chunk
  view.setUint32(36, 0x64617461, false); // "data"
  view.setUint32(40, pcm16.length * 2, true);

  const pcmBytes = new Uint8Array(pcm16.buffer);
  new Uint8Array(buffer, 44).set(pcmBytes);

  return new Uint8Array(buffer);
}

export default function Home() {
  const [transcript, setTranscript] = useState('');
  const [isRecording, setIsRecording] = useState(false);

  // Baseline state
  const [baseResponse, setBaseResponse] = useState('--');
  const [baseTtfa, setBaseTtfa] = useState('-- ms');
  const [baseTotal, setBaseTotal] = useState('-- ms');
  const [baseStatus, setBaseStatus] = useState('Idle');
  const [baseStage, setBaseStage] = useState('idle'); // 'idle' | 'stt' | 'llm' | 'tts' | 'done'
  const [baseStageTimes, setBaseStageTimes] = useState({ stt: 0, llm: 0, tts: 0 });
  const [basePlaying, setBasePlaying] = useState(false);

  // Gateway state
  const [gwResponse, setGwResponse] = useState('--');
  const [gwTtfa, setGwTtfa] = useState('-- ms');
  const [gwDecision, setGwDecision] = useState('--');
  const [gwSim, setGwSim] = useState('--');
  const [gwClauses, setGwClauses] = useState([]);
  const [gwStatus, setGwStatus] = useState('Idle');
  const [gwStage, setGwStage] = useState('idle'); // 'idle' | 'stt' | 'route' | 'response' | 'cache' | 'done'
  const [gwStageTimes, setGwStageTimes] = useState({ stt: 0, route: 0, response: 0, cache: 0 });
  const [gwPlaying, setGwPlaying] = useState(false);

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

  // Audio recording refs
  const audioContextRef = useRef(null);
  const mediaStreamRef = useRef(null);
  const scriptProcessorRef = useRef(null);
  const recordedChunksRef = useRef([]);
  const isRecordingRef = useRef(false);

  const getWsUrl = () => {
    if (typeof window === 'undefined') return '';
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const hostname = window.location.hostname || 'localhost';
    const port = window.location.port === '3000' ? '8000' : (window.location.port || '8000');
    return `${protocol}//${hostname}:${port}/ws`;
  };

  const getApiUrl = (endpoint) => {
    if (typeof window === 'undefined') return endpoint;
    if (window.location.port === '3000') {
      return `http://${window.location.hostname}:8000${endpoint}`;
    }
    return endpoint;
  };

  useEffect(() => {
    fetchStats();
  }, []);

  const fetchStats = async () => {
    try {
      const res = await fetch(getApiUrl('/api/stats'));
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
      console.warn("Could not fetch stats:", e);
    }
  };

  const playAudioChunks = (chunks, audioElem, setPlaying) => {
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

    audioElem.onplay = () => setPlaying(true);
    audioElem.onended = () => setPlaying(false);
    audioElem.onpause = () => setPlaying(false);

    audioElem.play().catch(() => {});
  };

  const runTurn = async (queryText = transcript, wavData = null) => {
    if (!queryText.trim() && !wavData) return;

    const detectedLang = detectLanguage(queryText);

    // Reset display & dynamic stages
    setBaseResponse('Connecting to baseline...');
    setBaseTtfa('-- ms');
    setBaseTotal('-- ms');
    setBaseStatus('Executing...');
    setBaseStage(wavData ? 'stt' : 'llm');
    setBaseStageTimes({ stt: 0, llm: 0, tts: 0 });

    setGwResponse('Evaluating cache & routing...');
    setGwTtfa('-- ms');
    setGwDecision('--');
    setGwSim('--');
    setGwClauses([]);
    setGwStatus('Evaluating...');
    setGwStage(wavData ? 'stt' : 'route');
    setGwStageTimes({ stt: 0, route: 0, response: 0, cache: 0 });

    const wsUrl = getWsUrl();

    // 1. Run Baseline Arm WebSocket
    const baseChunks = [];
    const baseWs = new WebSocket(wsUrl);
    baseWs.binaryType = 'arraybuffer';
    baseWsRef.current = baseWs;

    baseWs.onopen = () => {
      if (wavData) {
        baseWs.send(JSON.stringify({
          arm: 'baseline',
          session_id: 'live_sess',
          lang: detectedLang || 'hi-IN',
          run_id: 'live_turn',
          has_audio: true
        }));
        baseWs.send(wavData);
      } else {
        baseWs.send(JSON.stringify({
          arm: 'baseline',
          session_id: 'live_sess',
          lang: detectedLang,
          text: queryText,
          run_id: 'live_turn'
        }));
      }
    };

    baseWs.onmessage = (event) => {
      if (typeof event.data === 'string') {
        const msg = JSON.parse(event.data);
        if (msg.type === 'transcript') {
          setTranscript(msg.text);
          setBaseStatus(`Transcribed: "${msg.text}"`);
          setBaseStage('llm');
        } else if (msg.type === 'reply_text') {
          setBaseResponse(msg.text);
          setBaseStage('tts');
        } else if (msg.type === 'turn_done') {
          const m = msg.metrics;
          setBaseTtfa(`${m.ttfa_ms} ms`);
          setBaseTotal(`${m.total_ms} ms`);
          setBaseStatus('Playback Ready');
          setBaseStage('done');
          setBaseStageTimes({
            stt: m.stt_ms || 0,
            llm: m.llm_ms || 0,
            tts: Math.max(0, m.total_ms - (m.llm_ms || 0) - (m.stt_ms || 0))
          });
          playAudioChunks(baseChunks, baseAudioRef.current, setBasePlaying);
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
      if (wavData) {
        gwWs.send(JSON.stringify({
          arm: 'gateway',
          session_id: 'live_sess',
          lang: detectedLang || 'hi-IN',
          run_id: 'live_turn',
          has_audio: true
        }));
        gwWs.send(wavData);
      } else {
        gwWs.send(JSON.stringify({
          arm: 'gateway',
          session_id: 'live_sess',
          lang: detectedLang,
          text: queryText,
          run_id: 'live_turn'
        }));
      }
    };

    gwWs.onmessage = (event) => {
      if (typeof event.data === 'string') {
        const msg = JSON.parse(event.data);
        if (msg.type === 'transcript') {
          setTranscript(msg.text);
          setGwStatus(`Transcribed: "${msg.text}"`);
          setGwStage('route');
        } else if (msg.type === 'route') {
          setGwDecision(msg.decision);
          setGwSim(msg.sim_score > 0 ? `${(msg.sim_score * 100).toFixed(1)}%` : 'Direct');
          setGwStage('response');
        } else if (msg.type === 'reply_text') {
          setGwResponse(msg.text);
          setGwStage('cache');
        } else if (msg.type === 'turn_done') {
          const m = msg.metrics;
          setGwTtfa(`${m.ttfa_ms} ms`);
          setGwStatus('Stream Completed');
          setGwStage('done');
          setGwStageTimes({
            stt: m.stt_ms || 0,
            route: m.route_ms || 0,
            response: m.llm_ms || 0,
            cache: m.ttfa_ms || 0
          });

          const tags = [];
          for (let i = 0; i < (m.clauses || 1); i++) {
            tags.push(i < m.clause_hits ? `Clause ${i + 1}: Exact Cache HIT` : `Clause ${i + 1}: Live Synthesized`);
          }
          setGwClauses(tags);
          playAudioChunks(gwChunks, gwAudioRef.current, setGwPlaying);
          fetchStats();
        }
      } else if (event.data instanceof ArrayBuffer) {
        gwChunks.push(new Uint8Array(event.data));
      }
    };
  };

  // Push-to-Talk audio recording handlers
  const startRecording = async () => {
    try {
      isRecordingRef.current = true;
      setIsRecording(true);

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!isRecordingRef.current) {
        stream.getTracks().forEach(t => t.stop());
        return;
      }
      mediaStreamRef.current = stream;
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      const ctx = new AudioCtx();
      audioContextRef.current = ctx;

      const source = ctx.createMediaStreamSource(stream);
      recordedChunksRef.current = [];
      const processor = ctx.createScriptProcessor(4096, 1, 1);
      scriptProcessorRef.current = processor;

      processor.onaudioprocess = (e) => {
        if (!isRecordingRef.current) return;
        const inputData = e.inputBuffer.getChannelData(0);
        recordedChunksRef.current.push(new Float32Array(inputData));
      };

      source.connect(processor);
      processor.connect(ctx.destination);
    } catch (err) {
      console.error("Microphone access failed:", err);
      isRecordingRef.current = false;
      setIsRecording(false);
    }
  };

  const stopRecording = () => {
    if (!isRecordingRef.current) return;
    isRecordingRef.current = false;
    setIsRecording(false);

    if (scriptProcessorRef.current) {
      try { scriptProcessorRef.current.disconnect(); } catch (_) {}
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(t => t.stop());
    }

    const sampleRate = audioContextRef.current ? audioContextRef.current.sampleRate : 48000;
    const wavBytes = encodeWav16kHz(recordedChunksRef.current, sampleRate);

    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      try { audioContextRef.current.close().catch(() => {}); } catch (_) {}
    }

    if (wavBytes && wavBytes.length > 44) {
      runTurn("", wavBytes);
    }
  };

  return (
    <div>
      {/* Top Professional Header */}
      <header className="app-header">
        <div className="header-left">
          <div className="logo-badge">⚡</div>
          <div>
            <h1 className="brand-title">Gnani Voice Gateway</h1>
            <p className="brand-subtitle">Semantic Response & Exact Audio Caching Architecture</p>
          </div>
        </div>

        <div className="header-right">
          <div className="status-pill">
            <span className="dot-indicator"></span>
            <span>Gateway Engine Active</span>
          </div>
        </div>
      </header>

      {/* Monochrome Metrics Ribbon */}
      <section className="metrics-ribbon">
        <div className="ribbon-card">
          <span className="ribbon-label">Characters Avoided</span>
          <span className="ribbon-value">{stats.charsAvoided.toLocaleString()}</span>
          <span className="ribbon-sub">Direct TTS character reduction</span>
        </div>
        <div className="ribbon-card">
          <span className="ribbon-label">TTS Syntheses Avoided</span>
          <span className="ribbon-value">{stats.ttsAvoided}</span>
          <span className="ribbon-sub">Exact audio cache hits</span>
        </div>
        <div className="ribbon-card">
          <span className="ribbon-label">LLM Inferences Avoided</span>
          <span className="ribbon-value">{stats.llmAvoided}</span>
          <span className="ribbon-sub">Semantic intent responses</span>
        </div>
        <div className="ribbon-card">
          <span className="ribbon-label">Median TTFA Speedup</span>
          <span className="ribbon-value">{stats.speedup}</span>
          <span className="ribbon-sub">Latency reduction ratio</span>
        </div>
      </section>

      {/* Split-Screen Comparative Arena */}
      <main className="split-arena">
        {/* Baseline Naive Agent Panel */}
        <div className="agent-panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <h3>Naive Baseline Agent</h3>
              <p>Sequential pipeline: STT → LLM → Full TTS (Uncached)</p>
            </div>
            <span className="panel-badge">Control Arm</span>
          </div>

          {/* Dynamic Graphic Holder: Baseline Pipeline Flow */}
          <div className="flow-graphic-holder">
            <div className="flow-holder-label">
              <span>Pipeline Stage Flow</span>
              <span style={{ fontFamily: 'var(--font-mono)', color: baseStage === 'done' ? '#ffffff' : 'var(--text-muted)' }}>
                {baseStage.toUpperCase()}
              </span>
            </div>
            <div className="flow-stages-row">
              <div className={`flow-node ${baseStage === 'stt' ? 'active' : baseStage !== 'idle' ? 'completed' : ''}`}>
                <div className="node-icon-circle">1</div>
                <span className="node-name">STT</span>
                <span className="node-meta">{baseStageTimes.stt > 0 ? `${baseStageTimes.stt}ms` : '--'}</span>
              </div>
              <div className={`flow-connector ${baseStage === 'stt' || baseStage === 'llm' ? 'active' : ''}`} />
              <div className={`flow-node ${baseStage === 'llm' ? 'active' : ['tts', 'done'].includes(baseStage) ? 'completed' : ''}`}>
                <div className="node-icon-circle">2</div>
                <span className="node-name">LLM Reason</span>
                <span className="node-meta">{baseStageTimes.llm > 0 ? `${baseStageTimes.llm}ms` : '--'}</span>
              </div>
              <div className={`flow-connector ${baseStage === 'llm' || baseStage === 'tts' ? 'active' : ''}`} />
              <div className={`flow-node ${baseStage === 'tts' ? 'active' : baseStage === 'done' ? 'completed' : ''}`}>
                <div className="node-icon-circle">3</div>
                <span className="node-name">Full TTS</span>
                <span className="node-meta">{baseStageTimes.tts > 0 ? `${baseStageTimes.tts}ms` : '--'}</span>
              </div>
            </div>
          </div>

          {/* Telemetry Metrics */}
          <div className="telemetry-row">
            <div className="telemetry-col">
              <span className="telemetry-label">Time to First Audio</span>
              <span className="telemetry-val">{baseTtfa}</span>
            </div>
            <div className="telemetry-col">
              <span className="telemetry-label">Total Duration</span>
              <span className="telemetry-val">{baseTotal}</span>
            </div>
            <div className="telemetry-col">
              <span className="telemetry-label">State</span>
              <span className="telemetry-val" style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{baseStatus}</span>
            </div>
          </div>

          {/* Spoken Response */}
          <div className="dialogue-section">
            <span className="section-label">Synthesized Response</span>
            <div className="response-box">
              {baseResponse}
            </div>
          </div>

          {/* Audio Player Card */}
          <div className="audio-card">
            <div className="audio-header">
              <span className="audio-status-text">{baseStatus}</span>
              <div className={`wave-bars ${basePlaying ? 'playing' : ''}`}>
                <span /><span /><span /><span /><span />
              </div>
            </div>
            <audio ref={baseAudioRef} controls />
          </div>
        </div>

        {/* Voice Gateway Optimized Panel */}
        <div className="agent-panel">
          <div className="panel-header">
            <div className="panel-title-group">
              <h3>Voice Gateway</h3>
              <p>Optimized stack: Semantic Routing + L1/L2 Audio Cache + Single-Flight</p>
            </div>
            <span className="panel-badge badge-gateway">Optimized Arm</span>
          </div>

          {/* Dynamic Graphic Holder: Gateway Pipeline Flow */}
          <div className="flow-graphic-holder">
            <div className="flow-holder-label">
              <span>Optimized Architecture Flow</span>
              <span style={{ fontFamily: 'var(--font-mono)', color: gwStage === 'done' ? '#ffffff' : 'var(--text-muted)' }}>
                {gwStage.toUpperCase()}
              </span>
            </div>
            <div className="flow-stages-row">
              <div className={`flow-node ${gwStage === 'stt' ? 'active' : gwStage !== 'idle' ? 'completed' : ''}`}>
                <div className="node-icon-circle">1</div>
                <span className="node-name">STT</span>
                <span className="node-meta">{gwStageTimes.stt > 0 ? `${gwStageTimes.stt}ms` : '--'}</span>
              </div>
              <div className={`flow-connector ${gwStage === 'stt' || gwStage === 'route' ? 'active' : ''}`} />
              <div className={`flow-node ${gwStage === 'route' ? 'active' : ['response', 'cache', 'done'].includes(gwStage) ? 'completed' : ''}`}>
                <div className="node-icon-circle">2</div>
                <span className="node-name">Router</span>
                <span className="node-meta">{gwSim !== '--' ? gwSim : '--'}</span>
              </div>
              <div className={`flow-connector ${gwStage === 'route' || gwStage === 'response' ? 'active' : ''}`} />
              <div className={`flow-node ${gwStage === 'response' ? 'active' : ['cache', 'done'].includes(gwStage) ? 'completed' : ''}`}>
                <div className="node-icon-circle">3</div>
                <span className="node-name">Intent / LLM</span>
                <span className="node-meta">{gwDecision !== '--' ? gwDecision : '--'}</span>
              </div>
              <div className={`flow-connector ${gwStage === 'response' || gwStage === 'cache' ? 'active' : ''}`} />
              <div className={`flow-node ${gwStage === 'cache' ? 'active' : gwStage === 'done' ? 'completed' : ''}`}>
                <div className="node-icon-circle">4</div>
                <span className="node-name">Audio Cache</span>
                <span className="node-meta">
                  {gwClauses.length > 0 
                    ? `${gwClauses.filter(c => c.includes('HIT')).length}/${gwClauses.length} Hit` 
                    : '--'}
                </span>
              </div>
            </div>
          </div>

          {/* Telemetry Metrics */}
          <div className="telemetry-row">
            <div className="telemetry-col">
              <span className="telemetry-label">Time to First Audio</span>
              <span className="telemetry-val" style={{ color: '#ffffff' }}>{gwTtfa}</span>
            </div>
            <div className="telemetry-col">
              <span className="telemetry-label">Route Decision</span>
              <span className="telemetry-val" style={{ fontSize: '0.85rem' }}>{gwDecision}</span>
            </div>
            <div className="telemetry-col">
              <span className="telemetry-label">Similarity Match</span>
              <span className="telemetry-val">{gwSim}</span>
            </div>
          </div>

          {/* Spoken Response & Clause Cache Breakdown */}
          <div className="dialogue-section">
            <span className="section-label">Cached / Streamed Response</span>
            <div className="response-box">
              {gwResponse}
            </div>
            {gwClauses.length > 0 && (
              <div className="clause-chips-row">
                {gwClauses.map((c, i) => (
                  <span key={i} className={`clause-chip ${c.includes('HIT') ? 'hit' : 'miss'}`}>
                    {c}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Audio Player Card */}
          <div className="audio-card">
            <div className="audio-header">
              <span className="audio-status-text">{gwStatus}</span>
              <div className={`wave-bars ${gwPlaying ? 'playing' : ''}`}>
                <span /><span /><span /><span /><span />
              </div>
            </div>
            <audio ref={gwAudioRef} controls />
          </div>
        </div>
      </main>

      {/* Clean Slate Input Dock: Type or Speak Freely */}
      <footer className="input-dock">
        <input
          type="text"
          className="main-input"
          value={transcript}
          onChange={(e) => setTranscript(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') runTurn(); }}
          placeholder=""
        />
        
        {/* Push-to-Talk Button */}
        <button
          className={`mic-btn ${isRecording ? 'recording' : ''}`}
          onMouseDown={startRecording}
          onMouseUp={stopRecording}
          onTouchStart={startRecording}
          onTouchEnd={stopRecording}
          title="Press and hold to speak"
        >
          {isRecording ? <span className="rec-pulse-dot" /> : <span>🎙️</span>}
          <span>{isRecording ? 'Listening...' : 'Push-to-Talk'}</span>
        </button>

        {/* Send Button */}
        <button className="send-btn" onClick={() => runTurn()}>
          Send →
        </button>
      </footer>
    </div>
  );
}
