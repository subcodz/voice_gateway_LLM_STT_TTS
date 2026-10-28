"""Day-1 probe for Gnani TTS (REST + SSE) and STT. Logs latency and bytes per call.

Setup:
  pip install requests
  Windows PowerShell:  $env:GNANI_API_KEY="your-key"
  macOS/Linux:         export GNANI_API_KEY=your-key

Get a key at https://app.gnani.ai/voice/

Usage (start with ONE call to confirm auth, then run the rest):
  python probe.py --tts-rest --only hindi --runs 1
  python probe.py --tts-rest
  python probe.py --tts-sse
  python probe.py --stt clip_hi.wav:hi-IN clip_bn.wav:bn-IN
  python probe.py --tts-rest --text "नमस्ते।" --runs 1     (one custom sentence)

Optional env: GNANI_TTS_MODEL (default timbre-v2.5), GNANI_V3_VOICE (default Shivani,
used only when the model is timbre-v3.0), GNANI_SAMPLE_RATE (default 48000).

Credits are not returned in responses. Note your dashboard balance before and after a
batch, then divide by the number of calls to get cost per call.
"""
import argparse, base64, json, os, sys, time
import requests

SESSION = requests.Session()  # reuse connections like a real gateway would

KEY = os.environ.get("GNANI_API_KEY", "")
BASE = "https://api.vachana.ai"
MODEL = os.environ.get("GNANI_TTS_MODEL", "timbre-v2.5")
V3_VOICE = os.environ.get("GNANI_V3_VOICE", "Shivani")
RATE = int(os.environ.get("GNANI_SAMPLE_RATE", "48000"))
LOG = "probe_log.jsonl"

# (label, text, language, timbre-v2.5 voice). Voices are model-specific: a wrong
# model/voice pair returns 400 and the error lists the voices that model accepts.
CASES = [
    ("hindi", "नमस्ते, आपकी बिजली शाम तक वापस आ जाएगी।", "hi-IN", "Nalini"),
    ("bengali", "আপনার বিদ্যুৎ সংযোগ আজ রাতের মধ্যে ঠিক হয়ে যাবে।", "bn-IN", "Kirra"),
    ("hinglish", "Aapka bill ₹2,340 hai, kal tak pay kar dijiye.", "hi-en", "Poorvi"),
    ("benglish", "Apnar meter reading ta ami ekhuni check kore dichhi.", "bn-IN", "Kirra"),
    ("hindi_number", "आपका बकाया पचहत्तर हज़ार चार सौ चालीस रुपये है।", "hi-IN", "Nalini"),
]


def log(rec):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(rec)


def headers(json_body=False):
    h = {"X-API-Key-ID": KEY}
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def payload(text, language, voice):
    return {
        "text": text,
        "voice": V3_VOICE if MODEL == "timbre-v3.0" else voice,
        "model": MODEL,
        "language": language,
        "speed": 1.0,
        "audio_config": {"sample_rate": RATE, "num_channels": 1, "sample_width": 2,
                         "encoding": "linear_pcm", "container": "wav"},
    }


def parse_sse(lines):
    """Yield (event, data_string) for each SSE message."""
    event, data = None, []
    for line in lines:
        if line is None:
            continue
        if line == "":
            if event or data:
                yield event, "\n".join(data)
            event, data = None, []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
    if event or data:
        yield event, "\n".join(data)


def tts_rest(label, text, language, voice, run):
    p = payload(text, language, voice)
    t0 = time.perf_counter()
    r = SESSION.post(f"{BASE}/api/v1/tts/inference", headers=headers(True), json=p, timeout=60)
    ms = round((time.perf_counter() - t0) * 1000)
    if r.status_code != 200:
        log({"kind": "tts_rest", "label": label, "http": r.status_code, "body": r.text[:400]})
        return
    out = f"tts_rest_{label}_run{run}.wav"
    open(out, "wb").write(r.content)
    log({"kind": "tts_rest", "label": label, "model": MODEL, "voice": p["voice"],
         "language": language, "total_ms": ms, "bytes": len(r.content),
         "riff": r.content[:4] == b"RIFF", "chars": len(text), "saved": out})


def tts_sse(label, text, language, voice, run):
    p = payload(text, language, voice)
    t0 = time.perf_counter()
    first = None
    chunks = []
    with SESSION.post(f"{BASE}/api/v1/tts/sse", headers=headers(True), json=p,
                       stream=True, timeout=60) as r:
        if r.status_code != 200:
            log({"kind": "tts_sse", "label": label, "http": r.status_code, "body": r.text[:400]})
            return
        r.encoding = "utf-8"
        for event, data in parse_sse(r.iter_lines(decode_unicode=True)):
            try:
                d = json.loads(data) if data else {}
            except json.JSONDecodeError:
                continue
            if event == "chunk" and d.get("audio"):
                if first is None:
                    first = round((time.perf_counter() - t0) * 1000)
                chunks.append(base64.b64decode(d["audio"]))
            if event == "complete" or d.get("is_final"):
                break
    total = round((time.perf_counter() - t0) * 1000)
    out = f"tts_sse_{label}_run{run}.wav"
    open(out, "wb").write(b"".join(chunks))
    log({"kind": "tts_sse", "label": label, "model": MODEL, "voice": p["voice"],
         "language": language, "first_chunk_ms": first, "total_ms": total,
         "chunks": len(chunks), "chunks_with_riff_header": sum(c[:4] == b"RIFF" for c in chunks),
         "bytes": sum(len(c) for c in chunks), "chars": len(text), "saved": out})


def stt(path, lang):
    t0 = time.perf_counter()
    with open(path, "rb") as f:
        r = SESSION.post(f"{BASE}/stt/v3", headers=headers(),
                          files={"audio_file": (os.path.basename(path), f)},
                          data={"language_code": lang, "format": "transcribe"}, timeout=60)
    ms = round((time.perf_counter() - t0) * 1000)
    try:
        body = r.json()
    except ValueError:
        body = r.text[:400]
    log({"kind": "stt", "file": path, "lang": lang, "http": r.status_code,
         "wall_ms": ms, "response": body})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tts-rest", action="store_true")
    ap.add_argument("--tts-sse", action="store_true")
    ap.add_argument("--stt", nargs="*", default=[], help="file:lang pairs, e.g. a.wav:hi-IN")
    ap.add_argument("--only", help="run just one case label, e.g. hindi")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--text", help="one custom sentence instead of the built-in cases")
    ap.add_argument("--language", default="hi-IN", help="with --text (default hi-IN)")
    ap.add_argument("--voice", default="Nalini", help="with --text (default Nalini)")
    a = ap.parse_args()
    if not (a.tts_rest or a.tts_sse or a.stt):
        ap.print_help()
        sys.exit("\nNothing to do: pass --tts-rest, --tts-sse or --stt.")
    if not KEY:
        sys.exit("Set GNANI_API_KEY first (see the top of this file).")
    cases = [c for c in CASES if not a.only or c[0] == a.only]
    if a.text:
        cases = [("custom", a.text, a.language, a.voice)]
    for item in a.stt:
        path, lang = item.rsplit(":", 1)
        stt(path, lang)
    for label, text, language, voice in cases:
        for run in range(1, a.runs + 1):
            if a.tts_rest:
                tts_rest(label, text, language, voice, run)
            if a.tts_sse:
                tts_sse(label, text, language, voice, run)