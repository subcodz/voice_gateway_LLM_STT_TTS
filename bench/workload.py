"""Benchmark workload generator using Zipfian intent distributions.

Why this module exists:
Generates reproducible conversational workloads of 200 turns to simulate real-world
call center traffic. It samples intents according to Zipf power-law distributions at three
configurable skew levels (high skew = repetitive FAQ surge, low skew = long-tail variety),
interleaving 15% personalized queries under a fixed random seed.
"""

import json
import os
import random
from typing import List, Dict


def load_eval_utterances(eval_path: str = "data/eval_set.jsonl") -> Dict[str, List[dict]]:
    """Loads eval utterances grouped by intent_id."""
    if not os.path.exists(eval_path):
        # Fallback to resolve relative to this file's repository root
        candidate = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "eval_set.jsonl")
        if os.path.exists(candidate):
            eval_path = candidate

    intents_pool: Dict[str, List[dict]] = {}
    with open(eval_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            intent = item["intent"]
            intents_pool.setdefault(intent, []).append(item)
    return intents_pool


def generate_zipf_workload(
    num_turns: int = 200,
    skew: str = "medium",  # 'high' (s=1.8), 'medium' (s=1.2), 'low' (s=0.6)
    personal_ratio: float = 0.15,
    seed: int = 42,
    eval_path: str = "data/eval_set.jsonl"
) -> List[dict]:
    """Generates an ordered list of workload turns with deterministic random seed.
    
    Each turn is a dict:
    {"index": int, "text": str, "lang": str, "intent": str, "is_personal": bool}
    """
    rng = random.Random(seed)
    pool = load_eval_utterances(eval_path)

    # Separate personal and non-personal intents
    non_personal_intents = [
        "power_outage", "bill_payment_modes", "new_connection", "office_hours",
        "safety_emergency", "meter_reading_schedule", "solar_scheme", "voltage_issue",
        "energy_saving", "support_contact"
    ]
    personal_intents = ["bill_due_inquiry", "complaint_status"]

    # Filter pool to ensure existence
    available_np = [i for i in non_personal_intents if i in pool]
    available_p = [i for i in personal_intents if i in pool]

    # Zipf exponent
    s_map = {"high": 1.8, "medium": 1.2, "low": 0.6}
    s = s_map.get(skew, 1.2)

    # Zipf weights: w_k = 1 / (k^s)
    weights = [1.0 / ((i + 1) ** s) for i in range(len(available_np))]
    total_w = sum(weights)
    probs = [w / total_w for w in weights]

    workload = []
    for idx in range(num_turns):
        is_personal = rng.random() < personal_ratio

        if is_personal and available_p:
            chosen_intent = rng.choice(available_p)
            utterance_meta = rng.choice(pool[chosen_intent])
        else:
            # Sample non-personal intent by Zipf probability
            chosen_intent = rng.choices(available_np, weights=probs, k=1)[0]
            utterance_meta = rng.choice(pool[chosen_intent])

        workload.append({
            "index": idx + 1,
            "text": utterance_meta["text"],
            "lang": utterance_meta["lang"],
            "intent": chosen_intent,
            "is_personal": utterance_meta.get("is_personal", False),
            "skew": skew
        })

    return workload
