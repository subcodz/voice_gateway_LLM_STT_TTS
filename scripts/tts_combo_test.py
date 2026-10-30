import os, json, base64, requests

KEY = os.environ["GNANI_API_KEY"]
URL = "https://api.vachana.ai/api/v1/tts/sse"
TEXT = "The capital of France is Paris."

def attempt(lang, voice):
    payload = {
        "text": TEXT, "voice": voice, "model": "timbre-v2.5",
        "language": lang, "speed": 1.0,
        "audio_config": {"sample_rate": 48000, "num_channels": 1,
                         "sample_width": 2, "encoding": "linear_pcm",
                         "container": "wav"},
    }
    r = requests.post(URL, headers={"X-API-Key-ID": KEY,
                      "Content-Type": "application/json"},
                      json=payload, stream=True, timeout=60)
    if r.status_code != 200:
        return f"HTTP {r.status_code}: {r.text[:300]}"
    event, total, err = None, 0, None
    for line in r.iter_lines(decode_unicode=True):
        line = (line or "").strip()
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data = line[5:].strip()
            if event == "error":
                err = data
            elif event == "chunk":
                try:
                    total += len(base64.b64decode(json.loads(data).get("audio", "")))
                except Exception:
                    pass
    return f"error event: {err}" if err else f"ok, {total} audio bytes"

for lang, voice in [("hi-en", "Poorvi"), ("en-IN", "Poorvi"),
                    ("bn-IN", "Kirra"), ("hi-IN", "Nalini")]:
    print(f"{lang:6} {voice:7} -> {attempt(lang, voice)}")