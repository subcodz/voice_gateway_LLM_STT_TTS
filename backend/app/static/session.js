/**
 * Gnani Voice Gateway - Session demo client.
 *
 * One WebSocket (/ws/session). Per turn the server sends JSON events; every
 * {"type":"audio"} event is followed by exactly one binary frame with that chunk.
 * Audio is assembled per clause, its WAV header repaired, and played clause by clause.
 */

// Edit these to match data/intents.yaml. The path is: cold miss, different question,
// exact repeat (normalizes to turn 1), paraphrase (needs the real embedder), new question.
const GUIDED = [
  { label: "1  Bill payment", text: "How can I pay my electricity bill online?", hint: "Cold: nothing cached yet" },
  { label: "2  Office hours", text: "What are the office hours?", hint: "Different question" },
  { label: "3  Repeat of 1", text: "how can i pay my electricity bill online", hint: "Same query after normalization: exact hit" },
  { label: "4  Paraphrase of 1", text: "What are the ways to pay the electricity bill online?", hint: "Semantic hit if the similarity clears the threshold" },
  { label: "5  New question", text: "What should I do about voltage fluctuation?", hint: "Miss on the LLM, partial reuse is possible" },
];

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ------------------------------------------------------------------ audio helpers

function concat(parts) {
  const total = parts.reduce((n, p) => n + p.length, 0);
  const out = new Uint8Array(total);
  let off = 0;
  for (const p of parts) { out.set(p, off); off += p.length; }
  return out;
}

/** Port of app/audio.py fix_wav_header: rewrites the 0xFFFFFFFF streaming placeholders. */
function fixWav(u8) {
  const tag = (o) => String.fromCharCode(u8[o], u8[o + 1], u8[o + 2], u8[o + 3]);
  if (u8.length < 12 || tag(0) !== "RIFF" || tag(8) !== "WAVE") return u8;
  const out = u8.slice();
  const dv = new DataView(out.buffer);
  let pos = 12;
  while (pos + 8 <= out.length) {
    const id = String.fromCharCode(out[pos], out[pos + 1], out[pos + 2], out[pos + 3]);
    const size = dv.getUint32(pos + 4, true);
    if (id === "data") {
      dv.setUint32(4, out.length - 8, true);
      dv.setUint32(pos + 4, out.length - (pos + 8), true);
      return out;
    }
    pos += 8 + size + (size & 1);
  }
  return out;
}

const player = {
  audio: typeof Audio !== "undefined" ? new Audio() : null,
  queue: [], playing: false, lastUrl: null,
  enqueue(u8) {
    this.queue.push(URL.createObjectURL(new Blob([u8], { type: "audio/wav" })));
    if (!this.playing) this.next();
  },
  next() {
    if (this.lastUrl) { URL.revokeObjectURL(this.lastUrl); this.lastUrl = null; }
    const url = this.queue.shift();
    if (!url) { this.playing = false; return; }
    this.playing = true;
    this.lastUrl = url;
    this.audio.src = url;
    this.audio.play().catch(() => { this.playing = false; });
  },
  stop() { this.audio.pause(); this.queue = []; this.playing = false; },
  replay(clips) { this.stop(); clips.forEach((c) => c && this.enqueue(c)); },
};
if (player.audio) player.audio.onended = () => player.next();

// ------------------------------------------------------------------ state

let ws = null;
let sessionId = (typeof crypto !== "undefined" && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now());
let busy = false;
let mock = null;
let turns = [];
let cur = null;
let pendingHdr = null;
let snap = null;
const usedGuided = new Set();

// ------------------------------------------------------------------ websocket

function ensureWs() {
  if (ws && ws.readyState === WebSocket.OPEN) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/ws/session`);
    ws.binaryType = "arraybuffer";
    ws.onopen = () => resolve();
    ws.onerror = () => reject(new Error("Could not connect"));
    ws.onmessage = onMessage;
    ws.onclose = () => { ws = null; setBusy(false); setMode("disconnected"); };
  });
}

function onMessage(ev) {
  if (typeof ev.data !== "string") { onAudioBytes(new Uint8Array(ev.data)); return; }
  const m = JSON.parse(ev.data);
  switch (m.type) {
    case "ready": mock = m.mock; setMode(m.mock ? "mock APIs (no credits)" : "live Gnani"); break;
    case "turn_start": startTurn(m); break;
    case "reply": onReply(m); break;
    case "audio": pendingHdr = m; break;
    case "clause_done": onClauseDone(m); break;
    case "arm_done": onArmDone(m); break;
    case "turn_done": onTurnDone(m); break;
    case "cap": notice(m.message); if (cur && !cur.reply) turns.pop(); finishTurn(); break;
    case "error":
      notice(m.message);
      if (cur && !cur.reply) { cur.reply = "No reply could be generated."; cur.source = ""; }
      finishTurn(); break;
    default: break;
  }
}

async function sendTurn(text) {
  text = (text || "").trim();
  if (!text || busy) return;
  try { await ensureWs(); } catch (e) { notice("Could not reach the server."); return; }
  notice("");
  setBusy(true);
  ws.send(JSON.stringify({ type: "turn", session_id: sessionId, text }));
  $("msg").value = "";
}

function resetSession() {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "reset", session_id: sessionId }));
  sessionId = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
  turns = []; cur = null; snap = null; pendingHdr = null;
  usedGuided.clear();
  player.stop();
  notice("");
  setBusy(false);
  render();
}

// ------------------------------------------------------------------ event handlers

function blankArm() { return { chunks: {}, clips: [], src: [], m: null, firstAudioClientMs: null }; }

function startTurn(m) {
  cur = {
    n: m.turn, text: m.text, reply: null, source: null, sim: 0, replyAt: null, replyReadyMs: 0,
    cached: blankArm(), uncached: blankArm(), skipped: false, summary: null
  };
  turns.push(cur);
  player.stop();
  render();
}

function onReply(m) {
  if (!cur) return;
  Object.assign(cur, { reply: m.text, source: m.source, sim: m.sim_score, replyReadyMs: m.reply_ready_ms, replyAt: performance.now() });
  render();
}

function onAudioBytes(bytes) {
  if (!pendingHdr || !cur) return;
  const { arm, clause } = pendingHdr;
  pendingHdr = null;
  const a = cur[arm];
  (a.chunks[clause] = a.chunks[clause] || []).push(bytes);
  if (a.firstAudioClientMs === null && cur.replyAt) a.firstAudioClientMs = performance.now() - cur.replyAt;
}

function onClauseDone(m) {
  if (!cur) return;
  const a = cur[m.arm];
  const wav = fixWav(concat(a.chunks[m.clause] || []));
  a.clips[m.clause] = wav;
  a.src[m.clause] = m.source;
  delete a.chunks[m.clause];
  if (m.arm === "cached" && $("autoplay").checked) player.enqueue(wav);
  render();
}

function onArmDone(m) { if (cur) { cur[m.arm].m = m.metrics; render(); } }

function onTurnDone(m) {
  if (cur) cur.summary = m.turn_summary;
  snap = m.session;
  if (m.turn_summary && m.turn_summary.compared === false) notice("One audio path failed on this turn, so it is left out of the totals.");
  finishTurn();
}

function finishTurn() {
  if (cur && !cur.cached.m && !cur.uncached.m) cur.skipped = true;
  setBusy(false);
  render();
}

// ------------------------------------------------------------------ rendering

const SOURCE_LABEL = {
  llm: "LLM call", exact_hit: "LLM cache: exact hit", semantic_hit: "LLM cache: semantic hit",
  intent_cache: "Intent cache", llm_uncacheable: "LLM call (personal, never cached)", llm_failed: "LLM failed, fallback reply",
};
const fmtMs = (v) => (v === null || v === undefined) ? "--" : (v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`);
const fmtNum = (v) => Number(v || 0).toLocaleString();

function renderConvo() {
  if (!turns.length) { $("convo").innerHTML = `<span class="convo-empty">Pick a guided prompt below, or type your own.</span>`; return; }
  $("convo").innerHTML = turns.map((t) => {
    const hit = t.source === "exact_hit" || t.source === "semantic_hit" || t.source === "intent_cache";
    const label = SOURCE_LABEL[t.source] || "";
    const sim = t.source === "semantic_hit" ? ` ${(t.sim * 100).toFixed(1)}%` : "";
    return `<div class="turn">
      <div class="bubble user">${esc(t.text)}</div>
      <div class="bubble agent">${t.reply ? esc(t.reply) : "Thinking…"}</div>
      ${t.reply ? `<div class="llm-line"><span class="llm-badge ${hit ? "cachehit" : ""}">${esc(label)}${sim}</span>
        <span>reply ready in ${fmtMs(t.replyReadyMs)}</span></div>` : ""}
    </div>`;
  }).join("");
}

function armRow(t, arm) {
  const a = t[arm], m = a.m;
  const n = m ? m.clauses : a.src.length;
  const chips = [];
  for (let i = 0; i < Math.max(n, a.src.length); i++) {
    const s = a.src[i];
    chips.push(`<span class="chip ${s || ""}">Clause ${i + 1}: ${s ? s.toUpperCase() : "…"}</span>`);
  }
  if (t.skipped && !m) return `<div class="arm-row"><div class="arm-row-head"><span>Turn ${t.n}</span></div><div class="fine">Audio skipped (demo limit).</div></div>`;
  return `<div class="arm-row">
    <div class="arm-row-head"><span>Turn ${t.n}</span>${a.clips.some(Boolean) ? `<button class="mini" data-replay="${arm}" data-turn="${t.n}">Play</button>` : ""}</div>
    <div class="kv">
      <div><label>First sound</label><b>${m ? fmtMs(m.first_playable_ms) : "…"}</b></div>
      <div><label>Full audio</label><b>${m ? fmtMs(m.total_ms) : "…"}</b></div>
      <div><label>TTS chars</label><b>${m ? fmtNum(m.tts_chars) : "…"}</b></div>
      <div><label>TTS calls</label><b>${m ? m.tts_calls : "…"}</b></div>
    </div>
    <div class="chips">${chips.join("")}</div>
    ${m && m.error ? `<div class="err">Error: ${esc(m.error)}</div>` : ""}
    ${m ? `<div class="fine">first byte ${fmtMs(m.first_byte_ms)} · browser got audio ${fmtMs(a.firstAudioClientMs)} after the reply · unattributed ${fmtMs(m.unattributed_ms)}${m.noisy ? " · retries occurred, timing is noisy" : ""}</div>` : ""}
  </div>`;
}

function renderArms() {
  for (const arm of ["cached", "uncached"]) {
    $(`arm-${arm}`).innerHTML = turns.length
      ? turns.map((t) => armRow(t, arm)).reverse().join("") : `<div class="fine">No turns yet.</div>`;
  }
}

function renderSavings() {
  const el = $("savings");
  if (!snap || !snap.saved.compared_turns) {
    el.innerHTML = `<div class="card-header"><h3>Savings so far</h3></div><div class="fine">Totals appear after the first turn.</div>`;
    return;
  }
  const on = snap.arms.cached, off = snap.arms.uncached, s = snap.saved, n = Math.max(1, on.turns);
  const tn = Math.max(1, on.timed_turns);
  const timeRow = on.timed_turns ? null : "--";
  const pct = (saved, base) => base > 0 ? ` (${Math.round((saved / base) * 100)}%)` : "";
  const avg = (o, k) => o[k] / Math.max(1, o.turns);
  const row = (name, a, b, c, cls = "saved") => `<tr><td>${name}</td><td>${a}</td><td>${b}</td><td class="${cls}">${c}</td></tr>`;
  const hitRate = on.clauses ? `${Math.round((on.clause_hits / on.clauses) * 100)}%` : "--";
  const llm = snap.llm;

  const maxChars = Math.max(1, ...turns.map((t) => Math.max(t.cached.m ? t.cached.m.tts_chars : 0, t.uncached.m ? t.uncached.m.tts_chars : 0)));
  const bars = turns.filter((t) => t.cached.m && t.uncached.m).map((t) => `<div class="bar-row"><span>Turn ${t.n}</span>
    <div class="bar-pair">
      <div class="bar on" style="width:${(t.cached.m.tts_chars / maxChars) * 100}%" title="cache ON: ${t.cached.m.tts_chars} chars"></div>
      <div class="bar off" style="width:${(t.uncached.m.tts_chars / maxChars) * 100}%" title="cache OFF: ${t.uncached.m.tts_chars} chars"></div>
    </div></div>`).join("");

  el.innerHTML = `
    <div class="card-header"><h3>Savings so far (${on.turns} turn${on.turns === 1 ? "" : "s"})</h3></div>
    <table>
      <thead><tr><th>Metric</th><th>Cache ON</th><th>Cache OFF</th><th>Saved</th></tr></thead>
      <tbody>
        ${row("Characters sent to TTS", fmtNum(on.tts_chars), fmtNum(off.tts_chars), fmtNum(s.tts_chars) + pct(s.tts_chars, off.tts_chars))}
        ${row("Est. credits", on.est_credits.toFixed(2), off.est_credits.toFixed(2), s.est_credits.toFixed(2))}
        ${row("TTS calls", on.tts_calls, off.tts_calls, s.tts_calls + pct(s.tts_calls, off.tts_calls))}
        ${row("Avg time to first sound (hit turns only)", on.timed_turns ? fmtMs(on.first_playable_ms / tn) : "--", off.timed_turns ? fmtMs(off.first_playable_ms / tn) : "--", on.timed_turns ? fmtMs(s.first_playable_ms / tn) : "--")}
        ${row("Avg time to full audio (hit turns only)", on.timed_turns ? fmtMs(on.total_ms / tn) : "--", off.timed_turns ? fmtMs(off.total_ms / tn) : "--", on.timed_turns ? fmtMs(s.total_ms / tn) : "--")}
        ${row("Audio clause hit rate", hitRate, "0%", "", "")}
        ${row("LLM layer", `${llm.calls} LLM call${llm.calls === 1 ? "" : "s"} in ${snap.turns} turns`,
    "same text feeds both", `${llm.exact_hits} exact · ${llm.semantic_hits} semantic · ${llm.intent_hits} intent`, "")}
      </tbody>
    </table>
    <div class="bars">${bars}</div>
    <div class="legend"><span><i style="background:#fff"></i>cache ON chars per turn</span><span><i style="background:#52525b"></i>cache OFF chars per turn</span></div>
    <p class="fineprint">
      "First sound" is measured from the moment the reply text is final to the end of clause 1, a complete playable clip, identically for both paths.
      Both paths run at the same time against the same TTS provider.
      Credits are an estimate at ${snap.chars_per_credit} characters per credit (the measured ratio); the provider does not return credits per call.
      ${s.noisy_turns ? `${s.noisy_turns} turn(s) had retries, so their timings are noisy.` : ""}
    </p>`;
}

function renderRibbon() {
  const s = snap ? snap.saved : null;
  const off = snap ? snap.arms.uncached : null;
  $("r-chars").textContent = s ? fmtNum(s.tts_chars) : "0";
  $("r-chars-sub").textContent = s && off.tts_chars ? `${Math.round((s.tts_chars / off.tts_chars) * 100)}% of what cache-off sent` : "not sent to TTS";
  $("r-credits").textContent = s ? s.est_credits.toFixed(2) : "0";
  $("r-calls").textContent = s ? fmtNum(s.tts_calls) : "0";
  $("r-time").textContent = s ? fmtMs(s.first_playable_ms) : "0 ms";
}

function render() { renderConvo(); renderArms(); renderSavings(); renderRibbon(); }

// ------------------------------------------------------------------ small UI helpers

function setMode(text) { $("mode-badge").textContent = text; }
function notice(text) { const n = $("notice"); n.textContent = text || ""; n.classList.toggle("show", !!text); }
function setBusy(b) {
  busy = b;
  $("send").disabled = b;
  document.querySelectorAll(".gchip").forEach((c) => { c.disabled = b; });
}

function buildGuided() {
  $("guided").innerHTML = `<span class="lbl">Guided path</span>` + GUIDED.map((g, i) =>
    `<button class="gchip" data-g="${i}" title="${esc(g.hint)}">${esc(g.label)}</button>`).join("");
}

function init() {
  buildGuided();
  render();
  $("guided").addEventListener("click", (e) => {
    const b = e.target.closest(".gchip");
    if (!b || busy) return;
    const i = Number(b.dataset.g);
    usedGuided.add(i); b.classList.add("used");
    sendTurn(GUIDED[i].text);
  });
  $("send").addEventListener("click", () => sendTurn($("msg").value));
  $("msg").addEventListener("keydown", (e) => { if (e.key === "Enter") sendTurn($("msg").value); });
  $("new-session").addEventListener("click", () => { resetSession(); buildGuided(); });
  document.body.addEventListener("click", (e) => {
    const b = e.target.closest("[data-replay]");
    if (!b) return;
    const t = turns.find((x) => x.n === Number(b.dataset.turn));
    if (t) player.replay(t[b.dataset.replay].clips);
  });
  ensureWs().catch(() => setMode("offline"));
}

if (typeof document !== "undefined" && document.getElementById("convo")) {
  window.addEventListener("DOMContentLoaded", init);
}
if (typeof module !== "undefined") module.exports = { fixWav, concat };
