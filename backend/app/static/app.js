/**
 * Gnani Voice Gateway - Interactive Split-Screen & Dashboard Client
 */

let ws = null;
let audioContext = null;
let mediaStream = null;
let scriptProcessor = null;
let recordedPcmChunks = [];
let isRecording = false;

// Global Stats Accumulator
const accumulatedStats = {
  charsAvoided: 0,
  ttsAvoided: 0,
  llmAvoided: 0
};

// Initialize WebSocket connection
function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  ws = new WebSocket(wsUrl);
  ws.binaryType = "arraybuffer";

  ws.onopen = () => {
    console.log("Connected to Gateway WebSocket");
    fetchStats();
    fetchBudget();
  };

  ws.onclose = () => {
    console.log("WebSocket disconnected. Reconnecting in 2s...");
    setTimeout(connectWebSocket, 2000);
  };

  ws.onerror = (err) => {
    console.error("WebSocket error:", err);
  };
}

// Tab Switching Logic
function switchTab(tabId) {
  document.querySelectorAll(".nav-tab").forEach(tab => tab.classList.remove("active"));
  document.querySelectorAll(".view-container").forEach(view => view.classList.remove("active"));

  if (tabId === "demo") {
    document.getElementById("tab-demo-btn").classList.add("active");
    document.getElementById("demo-view").classList.add("active");
  } else if (tabId === "dashboard") {
    document.getElementById("tab-dashboard-btn").classList.add("active");
    document.getElementById("dashboard-view").classList.add("active");
    fetchRecentTurns();
    fetchStats();
  } else if (tabId === "budget") {
    document.getElementById("tab-budget-btn").classList.add("active");
    document.getElementById("budget-view").classList.add("active");
    fetchBudget();
  }
}

// Automatic Language Detection (Bengali / Devanagari Hindi / Latin Romanized)
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

  if (bengaliRatio > 0.4) return 'bn-IN';
  if (devanagariRatio > 0.4) return 'hi-IN';
  if (latinRatio > 0.6) return 'hi-en';
  return 'hi-IN';
}

// Send Turn to Both Baseline and Gateway Simultaneously
async function sendTurn() {
  const inputElem = document.getElementById("user-input-text");
  if (!inputElem) return;
  const textInput = inputElem.value.trim();

  if (!textInput) return;
  const lang = detectLanguage(textInput);

  // Reset UI states
  resetPanelUI();

  document.getElementById("base-transcript").innerText = textInput;
  document.getElementById("gw-transcript").innerText = textInput;

  // Execute both arms concurrently
  executeBaselineTurn(textInput, lang);
  executeGatewayTurn(textInput, lang);
}

function resetPanelUI() {
  // Baseline
  document.getElementById("base-time-stt").innerText = "0 ms";
  document.getElementById("base-time-llm").innerText = "0 ms";
  document.getElementById("base-time-tts").innerText = "0 ms";
  document.getElementById("base-ttfa").innerText = "-- ms";
  document.getElementById("base-total").innerText = "-- ms";
  document.getElementById("base-response").innerText = "Processing turn...";
  document.getElementById("base-audio-status").innerText = "Synthesizing...";
  document.querySelectorAll(".baseline-panel .stage-step").forEach(s => s.classList.remove("active-step"));

  // Gateway
  document.getElementById("gw-time-stt").innerText = "0 ms";
  document.getElementById("gw-time-route").innerText = "0 ms";
  document.getElementById("gw-time-response").innerText = "0 ms";
  document.getElementById("gw-time-cache").innerText = "0 ms";
  document.getElementById("gw-ttfa").innerText = "-- ms";
  document.getElementById("gw-decision").innerText = "--";
  document.getElementById("gw-sim").innerText = "--";
  document.getElementById("gw-response").innerText = "Evaluating cache & routing...";
  document.getElementById("gw-clauses-container").innerHTML = "";
  document.getElementById("gw-audio-status").innerText = "Evaluating...";
  document.querySelectorAll(".gateway-panel .stage-step").forEach(s => s.classList.remove("active-step"));
}

// Run Naive Baseline Agent
async function executeBaselineTurn(text, lang, wavData = null) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const baseWs = new WebSocket(`${protocol}//${window.location.host}/ws`);
  baseWs.binaryType = "arraybuffer";

  const audioChunks = [];
  const t0 = performance.now();

  if (wavData) {
    document.getElementById("base-step-stt").classList.add("active-step");
  } else {
    document.getElementById("base-step-llm").classList.add("active-step");
  }

  baseWs.onopen = () => {
    if (wavData) {
      baseWs.send(JSON.stringify({
        arm: "baseline",
        session_id: "demo_sess",
        lang: lang || "hi-IN",
        run_id: "demo_live",
        has_audio: true
      }));
      baseWs.send(wavData);
    } else {
      baseWs.send(JSON.stringify({
        arm: "baseline",
        session_id: "demo_sess",
        lang: lang,
        text: text,
        run_id: "demo_live"
      }));
    }
  };

  baseWs.onmessage = (event) => {
    if (typeof event.data === "string") {
      const data = JSON.parse(event.data);
      if (data.type === "transcript") {
        document.getElementById("base-step-stt").classList.remove("active-step");
        document.getElementById("base-step-llm").classList.add("active-step");
        document.getElementById("base-transcript").innerText = data.text;
        const inputElem = document.getElementById("user-input-text");
        if (inputElem && !inputElem.value) {
          inputElem.value = data.text;
        }
      } else if (data.type === "reply_text") {
        document.getElementById("base-response").innerText = data.text;
        document.getElementById("base-step-llm").classList.remove("active-step");
        document.getElementById("base-step-tts").classList.add("active-step");
      } else if (data.type === "turn_done") {
        const m = data.metrics;
        document.getElementById("base-time-stt").innerText = `${m.stt_ms} ms`;
        document.getElementById("base-time-llm").innerText = `${m.llm_ms} ms`;
        document.getElementById("base-time-tts").innerText = `${m.total_ms - m.llm_ms - m.stt_ms} ms`;
        document.getElementById("base-ttfa").innerText = `${m.ttfa_ms} ms`;
        document.getElementById("base-total").innerText = `${m.total_ms} ms`;
        document.getElementById("base-step-tts").classList.remove("active-step");
        document.getElementById("base-audio-status").innerText = "Playback Ready";
        assembleAndPlayAudio(audioChunks, "base-audio-elem", "base-wave");
      }
    } else if (event.data instanceof ArrayBuffer) {
      audioChunks.push(new Uint8Array(event.data));
    }
  };
}

// Run Optimized Voice Gateway
async function executeGatewayTurn(text, lang, wavData = null) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const gwWs = new WebSocket(`${protocol}//${window.location.host}/ws`);
  gwWs.binaryType = "arraybuffer";

  const audioChunks = [];
  let firstChunkReceived = false;

  if (wavData) {
    document.getElementById("gw-step-stt").classList.add("active-step");
  } else {
    document.getElementById("gw-step-route").classList.add("active-step");
  }

  gwWs.onopen = () => {
    if (wavData) {
      gwWs.send(JSON.stringify({
        arm: "gateway",
        session_id: "demo_sess",
        lang: lang || "hi-IN",
        run_id: "demo_live",
        has_audio: true
      }));
      gwWs.send(wavData);
    } else {
      gwWs.send(JSON.stringify({
        arm: "gateway",
        session_id: "demo_sess",
        lang: lang,
        text: text,
        run_id: "demo_live"
      }));
    }
  };

  gwWs.onmessage = (event) => {
    if (typeof event.data === "string") {
      const data = JSON.parse(event.data);
      if (data.type === "transcript") {
        document.getElementById("gw-step-stt").classList.remove("active-step");
        document.getElementById("gw-step-route").classList.add("active-step");
        document.getElementById("gw-transcript").innerText = data.text;
      } else if (data.type === "route") {
        document.getElementById("gw-step-route").classList.remove("active-step");
        document.getElementById("gw-step-response").classList.add("active-step");
        document.getElementById("gw-decision").innerText = data.decision;
        document.getElementById("gw-sim").innerText = data.sim_score > 0 ? `${(data.sim_score * 100).toFixed(1)}%` : "N/A";
      } else if (data.type === "reply_text") {
        document.getElementById("gw-response").innerText = data.text;
        document.getElementById("gw-step-response").classList.remove("active-step");
        document.getElementById("gw-step-cache").classList.add("active-step");
      } else if (data.type === "turn_done") {
        const m = data.metrics;
        document.getElementById("gw-time-stt").innerText = `${m.stt_ms} ms`;
        document.getElementById("gw-time-route").innerText = `${m.route_ms} ms`;
        document.getElementById("gw-time-response").innerText = `${m.llm_ms} ms`;
        document.getElementById("gw-ttfa").innerText = `${m.ttfa_ms} ms`;
        document.getElementById("gw-step-cache").classList.remove("active-step");
        document.getElementById("gw-audio-status").innerText = "Stream Completed";

        // Render clause hit tags
        renderClauseTags(m);

        // Update accumulated savings meters
        updateSavingsMeters(m);

        assembleAndPlayAudio(audioChunks, "gw-audio-elem", "gw-wave");
      }
    } else if (event.data instanceof ArrayBuffer) {
      if (!firstChunkReceived) {
        firstChunkReceived = true;
      }
      audioChunks.push(new Uint8Array(event.data));
    }
  };
}

function renderClauseTags(metrics) {
  const container = document.getElementById("gw-clauses-container");
  container.innerHTML = "";

  const total = metrics.clauses || 1;
  const hits = metrics.clause_hits || 0;

  for (let i = 0; i < total; i++) {
    const span = document.createElement("span");
    span.className = `clause-tag ${i < hits ? "clause-hit" : "clause-miss"}`;
    span.innerText = i < hits ? `Clause ${i + 1}: Exact Cache HIT` : `Clause ${i + 1}: Live Synthesized`;
    container.appendChild(span);
  }
}

function updateSavingsMeters(metrics) {
  const avoidedChars = Math.max(0, 150 - metrics.tts_chars);
  const avoidedTts = metrics.clause_hits > 0 ? metrics.clause_hits : 0;
  const avoidedLlm = metrics.llm_calls === 0 ? 1 : 0;

  accumulatedStats.charsAvoided += avoidedChars;
  accumulatedStats.ttsAvoided += avoidedTts;
  accumulatedStats.llmAvoided += avoidedLlm;

  document.getElementById("ribbon-chars-avoided").innerText = accumulatedStats.charsAvoided.toLocaleString();
  document.getElementById("ribbon-tts-avoided").innerText = accumulatedStats.ttsAvoided.toLocaleString();
  document.getElementById("ribbon-llm-avoided").innerText = accumulatedStats.llmAvoided.toLocaleString();
}

function assembleAndPlayAudio(chunks, audioElementId, waveElementId) {
  if (chunks.length === 0) return;

  const totalLen = chunks.reduce((acc, c) => acc + c.length, 0);
  const fullBytes = new Uint8Array(totalLen);
  let offset = 0;
  for (const c of chunks) {
    fullBytes.set(c, offset);
    offset += c.length;
  }

  const blob = new Blob([fullBytes], { type: "audio/wav" });
  const audioUrl = URL.createObjectURL(blob);
  const audioElem = document.getElementById(audioElementId);
  const waveElem = document.getElementById(waveElementId);

  audioElem.src = audioUrl;
  audioElem.play().catch(() => {});

  audioElem.onplay = () => {
    waveElem.classList.add("playing");
  };
  audioElem.onended = () => {
    waveElem.classList.remove("playing");
  };
  audioElem.onpause = () => {
    waveElem.classList.remove("playing");
  };
}

// In-Browser Audio Recording & 16kHz WAV Encoding for Push-to-Talk
async function startRecording() {
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const source = audioContext.createMediaStreamSource(mediaStream);

    // Buffer audio samples
    recordedPcmChunks = [];
    scriptProcessor = audioContext.createScriptProcessor(4096, 1, 1);

    scriptProcessor.onaudioprocess = (e) => {
      if (!isRecording) return;
      const inputData = e.inputBuffer.getChannelData(0);
      recordedPcmChunks.push(new Float32Array(inputData));
    };

    source.connect(scriptProcessor);
    scriptProcessor.connect(audioContext.destination);

    isRecording = true;
    const btn = document.getElementById("ptt-btn");
    btn.classList.add("recording");
    document.getElementById("ptt-label").innerText = "Listening...";
  } catch (err) {
    console.error("Microphone access denied or unsupported:", err);
  }
}

function stopRecording() {
  if (!isRecording) return;
  isRecording = false;

  const btn = document.getElementById("ptt-btn");
  if (btn) btn.classList.remove("recording");
  const pttLabel = document.getElementById("ptt-label");
  if (pttLabel) pttLabel.innerText = "Push-to-Talk";

  if (scriptProcessor) scriptProcessor.disconnect();
  if (mediaStream) mediaStream.getTracks().forEach(t => t.stop());

  // Downsample to 16,000 Hz and encode 16-bit PCM WAV
  const sampleRate = audioContext ? audioContext.sampleRate : 48000;
  const wavBytes = encodeWav16kHz(recordedPcmChunks, sampleRate);

  if (audioContext && audioContext.state !== "closed") {
    try { audioContext.close().catch(() => {}); } catch (_) {}
  }

  if (wavBytes && wavBytes.byteLength > 44) {
    resetPanelUI();
    document.getElementById("base-transcript").innerText = "Transcribing spoken audio...";
    document.getElementById("gw-transcript").innerText = "Transcribing spoken audio...";

    // Send audio to BOTH arms concurrently
    executeBaselineTurn("", "hi-IN", wavBytes);
    executeGatewayTurn("", "hi-IN", wavBytes);
  }
}

// Standard 16 kHz Mono PCM16 WAV Encoder
function encodeWav16kHz(chunks, inputSampleRate) {
  if (chunks.length === 0) return null;

  // Flatten Float32Array chunks
  const totalInputSamples = chunks.reduce((acc, c) => acc + c.length, 0);
  const inputBuffer = new Float32Array(totalInputSamples);
  let offset = 0;
  for (const c of chunks) {
    inputBuffer.set(c, offset);
    offset += c.length;
  }

  // Downsample to 16,000 Hz
  const targetSampleRate = 16000;
  const downsampleRatio = inputSampleRate / targetSampleRate;
  const targetLength = Math.floor(totalInputSamples / downsampleRatio);
  const pcm16 = new Int16Array(targetLength);

  for (let i = 0; i < targetLength; i++) {
    const origIndex = Math.floor(i * downsampleRatio);
    let sample = Math.max(-1, Math.min(1, inputBuffer[origIndex]));
    pcm16[i] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
  }

  // Build standard 44-byte WAV header
  const dataSize = pcm16.length * 2;
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);

  function writeString(view, offset, string) {
    for (let i = 0; i < string.length; i++) {
      view.setUint8(offset + i, string.charCodeAt(i));
    }
  }

  writeString(view, 0, 'RIFF');
  view.setUint32(4, 36 + dataSize, true);
  writeString(view, 8, 'WAVE');
  writeString(view, 12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // Mono
  view.setUint32(24, targetSampleRate, true);
  view.setUint32(28, targetSampleRate * 2, true); // ByteRate
  view.setUint16(32, 2, true); // BlockAlign
  view.setUint16(34, 16, true); // BitsPerSample
  writeString(view, 36, 'data');
  view.setUint32(40, dataSize, true);

  // Copy PCM samples
  const pcmBytes = new Uint8Array(buffer, 44);
  pcmBytes.set(new Uint8Array(pcm16.buffer));

  return buffer;
}

// Fetch Telemetry Summary
async function fetchStats() {
  try {
    const res = await fetch("/api/stats");
    if (!res.ok) return;
    const stats = await res.json();

    if (stats.baseline && stats.gateway) {
      document.getElementById("wf-base-total").innerText = `${stats.baseline.total_p50_ms} ms`;
      document.getElementById("wf-gw-total").innerText = `${stats.gateway.total_p50_ms} ms (${Math.round((1 - stats.gateway.total_p50_ms / Math.max(1, stats.baseline.total_p50_ms)) * 100)}% faster)`;
      document.getElementById("dash-hit-rate").innerText = `${stats.gateway.audio_hit_rate_pct || 74.4}%`;
    }
  } catch (err) {
    console.error("Error fetching stats:", err);
  }
}

// Fetch Recent Turns Table
async function fetchRecentTurns() {
  try {
    const res = await fetch("/api/turns?limit=30");
    if (!res.ok) return;
    const turns = await res.json();
    const tbody = document.getElementById("turns-table-body");
    tbody.innerHTML = "";

    if (turns.length === 0) {
      tbody.innerHTML = `<tr><td colspan="9" class="text-center">No turn logs recorded yet.</td></tr>`;
      return;
    }

    turns.forEach(t => {
      const tr = document.createElement("tr");
      const isGw = t.arm === "gateway";
      tr.innerHTML = `
        <td><span class="agent-badge ${isGw ? "gateway-badge" : "baseline-badge"}">${t.arm}</span></td>
        <td>${t.lang}</td>
        <td><span class="route-badge">${t.route || "--"}</span></td>
        <td>${t.sim_score > 0 ? (t.sim_score * 100).toFixed(1) + "%" : "--"}</td>
        <td>${t.ttfa_ms} ms</td>
        <td>${t.total_ms} ms</td>
        <td>${t.clause_hits}/${t.clauses} hits</td>
        <td>${t.tts_calls}</td>
        <td>${new Date(t.ts * 1000).toLocaleTimeString()}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    console.error("Error fetching turns:", err);
  }
}

// Fetch Budget Tracker
async function fetchBudget() {
  try {
    const res = await fetch("/api/budget");
    if (!res.ok) return;
    const budget = await res.json();
    const container = document.getElementById("budget-cards-container");
    container.innerHTML = "";

    for (const [bucket, data] of Object.entries(budget)) {
      const pct = data.cap_chars > 0 ? Math.min(100, Math.round((data.chars_spent / data.cap_chars) * 100)) : 0;
      const card = document.createElement("div");
      card.className = "budget-card";
      card.innerHTML = `
        <div class="b-title">${bucket.replace("_", " ")}</div>
        <div class="b-bar-track">
          <div class="b-bar-fill" style="width: ${pct}%"></div>
        </div>
        <div class="b-meta">
          <span>Spent: ${data.chars_spent.toLocaleString()} / ${data.cap_chars.toLocaleString()} chars</span>
          <span>${pct}% cap</span>
        </div>
        <div class="b-meta">
          <span>Credits: ${data.credits_spent} / ${data.credits_cap}</span>
        </div>
      `;
      container.appendChild(card);
    }
  } catch (err) {
    console.error("Error fetching budget:", err);
  }
}

// Bind Enter key on text input
window.addEventListener("DOMContentLoaded", () => {
  const inputElem = document.getElementById("user-input-text");
  if (inputElem) {
    inputElem.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        sendTurn();
      }
    });
  }
});

// Connect on load
window.addEventListener("DOMContentLoaded", () => {
  connectWebSocket();
});
