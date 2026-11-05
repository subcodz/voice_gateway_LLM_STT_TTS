"""Calibrate the intent-cache threshold and margin against real embeddings.

Run from the repo root (uses the real embedder unless EMBEDDER=mock is set):
    python scripts/calibrate_intents.py

What it prints:
  1. Out-of-domain queries (should NOT hit the intent cache): top intent, top score,
     runner-up score, margin.
  2. In-domain queries from data/eval_set.jsonl (non-personal intents): how often the
     right intent is on top, and the score distribution.
  3. A suggested SEMANTIC_THRESHOLD, or a warning if the two groups overlap.

Caveat: eval_set utterances may be close to the intent examples, so the in-domain
scores are optimistic. Add your own real paraphrases to POSITIVES_EXTRA.
"""

import json
import statistics
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.cache.semantic import SemanticCache, cosine_similarity  # noqa: E402
from app.routing.intents import IntentCatalog  # noqa: E402
from app.routing.router import detect_language  # noqa: E402

# (text, lang or None to auto-detect)
NEGATIVES = [
    ("bharat er moddhe shobcheye bhalo ghurte jawar jaayga", None),
    ("amar ekta joke shunte iccha korche", None),
    ("kal cricket match er score koto", None),
    ("ভারতের সবচেয়ে ভালো ঘুরতে যাওয়ার জায়গা কোনটা", "bn-IN"),
    ("আজকের আবহাওয়া কেমন", "bn-IN"),
    ("আমাকে একটা গল্প বলো", "bn-IN"),
    ("भारत में घूमने की सबसे अच्छी जगह कौन सी है", "hi-IN"),
    ("आज मौसम कैसा है", "hi-IN"),
    ("mujhe ek joke sunao", "hi-en"),
    ("what is the best place to visit in india", "hi-en"),
    ("who won the world cup", "hi-en"),
]

# (text, lang, expected_intent_id): add real paraphrases of your intents here
POSITIVES_EXTRA = []


def ranked_scores(cache, query, lang):
    """Best example score per intent for this language, highest first."""
    qvec = cache.embed_text(query, is_query=True)
    out = []
    for (intent_id, entry_lang), entry in cache._entries.items():
        if entry_lang.lower() != lang.lower():
            continue
        best = max((cosine_similarity(qvec, v) for v in entry.embeddings), default=-1.0)
        out.append((intent_id, best))
    return sorted(out, key=lambda x: x[1], reverse=True)


def percentile(values, p):
    s = sorted(values)
    return s[min(len(s) - 1, int(len(s) * p))]


def main():
    catalog = IntentCatalog(str(ROOT / "data" / "intents.yaml"))
    cache = SemanticCache(threshold=0.0)
    catalog.populate_semantic_cache(cache)
    print(f"Embedder: {cache.embedder_name}\n")

    print("OUT-OF-DOMAIN (should miss)")
    print(f"{'lang':<6}{'top intent':<24}{'top':>7}{'2nd':>7}{'margin':>8}  query")
    neg_tops = []
    for text, lang in NEGATIVES:
        lang = lang or detect_language(text, fallback="hi-IN")
        r = ranked_scores(cache, text, lang)
        if not r:
            continue
        top, second = r[0][1], (r[1][1] if len(r) > 1 else 0.0)
        neg_tops.append(top)
        print(f"{lang:<6}{r[0][0]:<24}{top:>7.3f}{second:>7.3f}{top - second:>8.3f}  {text}")

    rows = []
    eval_path = ROOT / "data" / "eval_set.jsonl"
    if eval_path.exists():
        for line in eval_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                if not d.get("is_personal") and d["intent"] in catalog.intents:
                    rows.append((d["text"], d["lang"], d["intent"]))
    rows += POSITIVES_EXTRA

    pos_tops, pos_margins, wrong = [], [], 0
    for text, lang, expected in rows:
        r = ranked_scores(cache, text, lang)
        if not r:
            continue
        if r[0][0] != expected:
            wrong += 1
            continue
        pos_tops.append(r[0][1])
        pos_margins.append(r[0][1] - (r[1][1] if len(r) > 1 else 0.0))

    print(f"\nIN-DOMAIN: {len(rows)} utterances, wrong top intent: {wrong}")
    if not pos_tops:
        print("No usable in-domain rows. Add POSITIVES_EXTRA or check data/eval_set.jsonl.")
        return
    print(f"  top score  min {min(pos_tops):.3f}  p10 {percentile(pos_tops, 0.10):.3f}  "
          f"median {statistics.median(pos_tops):.3f}")
    print(f"  margin     min {min(pos_margins):.3f}  median {statistics.median(pos_margins):.3f}")

    neg_max = max(neg_tops) if neg_tops else 0.0
    pos_p10 = percentile(pos_tops, 0.10)
    print(f"\nHighest out-of-domain score: {neg_max:.3f}   Lowest-decile in-domain score: {pos_p10:.3f}")
    if neg_max < pos_p10:
        print(f"Groups separate. Suggested SEMANTIC_THRESHOLD = {(neg_max + pos_p10) / 2:.3f}")
    else:
        print("Groups overlap, so a threshold alone cannot fix it. Raise the threshold above "
              f"{neg_max:.3f} and also set SEMANTIC_MARGIN (try 0.02 to 0.03), then re-run.")


if __name__ == "__main__":
    main()
