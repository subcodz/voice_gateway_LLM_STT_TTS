#!/usr/bin/env python3
"""Evaluate the rule-based router on a labeled utterance set.

Usage (from the repo root):
    python scripts/eval_router.py                    # current rules, data/router_eval.jsonl
    python scripts/eval_router.py --legacy           # the old substring router, for comparison
    python scripts/eval_router.py --include-intents  # also score data/eval_set.jsonl
    python scripts/eval_router.py --quiet            # summary only, no miss list

Labels: personalized, heavy_llm, general (general means neither rule fires, so the
query continues to the semantic cache / fast LLM). Only the rule layer is scored,
so no embedding model or API key is needed.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

LABELS = ["personalized", "heavy_llm", "general"]

# ---- the original substring router, kept only so results can be compared ----
_LEGACY_PERSONAL = [
    "আমার বিল", "আমার বকেয়া", "मेरा बिल", "बकाया बिल", "my bill",
    "মিটার নম্বর", "मीटर नंबर", "meter number", "অভিযোগ নম্বর",
    "शिकायत संख्या", "complaint number", "status", "স্ট্যাটাস", "खाता", "account",
    "বিল কত", "কত বিল", "কত টাকা বিল", "বকেয়া কত", "লাস্ট ডেট", "last date", "due date",
    "অভিযোগের কি", "কমপ্লেন এর", "কি হলো আমার",
]
_LEGACY_POSSESSIVES = ["আমার", "मेरा", "मेरी", "मेरे", "my", "amar"]
_LEGACY_ACCOUNT = ["বিল", "বকেয়া", "মিটার", "কমপ্লেন", "অভিযোগ", "bill", "meter", "complaint", "due"]
_LEGACY_ESCALATION = [
    "আদালত", "পুলিশ", "legal", "dispute", "court", "ক্ষতিপূরণ",
    "मुआवजा", "विवाद", "fir", "threat",
]


def legacy_classify(text: str) -> str:
    t = text.strip().lower()
    for kw in _LEGACY_PERSONAL:
        if kw.lower() in t:
            return "personalized"
    if any(p in t for p in _LEGACY_POSSESSIVES) and any(a in t for a in _LEGACY_ACCOUNT):
        return "personalized"
    for kw in _LEGACY_ESCALATION:
        if kw.lower() in t:
            return "heavy_llm"
    return "general"


def load_rows(path: Path):
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main():
    # Bengali / Hindi text must print on Windows consoles and when piped to a file.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", default=str(ROOT / "data" / "router_eval.jsonl"))
    ap.add_argument("--rules", default=None, help="path to routing_rules.yaml")
    ap.add_argument("--legacy", action="store_true", help="score the old substring router")
    ap.add_argument("--include-intents", action="store_true",
                    help="also score data/eval_set.jsonl (is_personal -> personalized, else general)")
    ap.add_argument("--quiet", action="store_true", help="hide the list of misses")
    args = ap.parse_args()

    rows = load_rows(Path(args.eval))
    if args.include_intents:
        for r in load_rows(ROOT / "data" / "eval_set.jsonl"):
            rows.append({
                "text": r["text"], "lang": r["lang"],
                "expected": "personalized" if r.get("is_personal") else "general",
                "notes": f"eval_set intent={r.get('intent')}",
            })

    if args.legacy:
        classify = legacy_classify
        name = "legacy substring router"
    else:
        from app.routing.rules import RoutingRules
        rules = RoutingRules.load(args.rules)

        def classify(text: str) -> str:
            hit = rules.classify(text)
            return hit.label if hit else "general"
        name = "rule engine (data/routing_rules.yaml)"

    confusion = defaultdict(Counter)  # expected -> predicted -> count
    misses = []
    for r in rows:
        pred = classify(r["text"])
        confusion[r["expected"]][pred] += 1
        if pred != r["expected"]:
            misses.append((r, pred))

    total = len(rows)
    correct = total - len(misses)
    print(f"Scorer: {name}")
    print(f"Utterances: {total}   Accuracy: {correct}/{total} = {correct / total:.1%}\n")

    print(f"{'class':<14}{'precision':>10}{'recall':>9}{'f1':>8}{'support':>9}")
    for lab in LABELS:
        tp = confusion[lab][lab]
        fp = sum(confusion[o][lab] for o in LABELS if o != lab)
        fn = sum(confusion[lab][p] for p in LABELS if p != lab)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        print(f"{lab:<14}{prec:>10.2f}{rec:>9.2f}{f1:>8.2f}{tp + fn:>9}")

    print("\nConfusion (rows = expected, columns = predicted)")
    print(f"{'':<14}" + "".join(f"{p:>14}" for p in LABELS))
    for e in LABELS:
        print(f"{e:<14}" + "".join(f"{confusion[e][p]:>14}" for p in LABELS))

    if misses and not args.quiet:
        print(f"\nMisses ({len(misses)})")
        for r, pred in misses:
            print(f"  expected {r['expected']:<12} got {pred:<12} [{r['lang']}] {r['text']}")
            if r.get("notes"):
                print(f"      note: {r['notes']}")


if __name__ == "__main__":
    main()