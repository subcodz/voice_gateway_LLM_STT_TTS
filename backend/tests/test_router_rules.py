"""Tests for the word-aware routing rules (personal guardrail and escalation)."""

import json
from pathlib import Path

import pytest

from app.cache.semantic import SemanticCache
from app.routing.intents import IntentCatalog
from app.routing.router import Router
from app.routing.rules import RoutingRules, tokenize

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def rules():
    return RoutingRules.load()


def label(rules, text):
    hit = rules.classify(text)
    return hit.label if hit else "general"


# Sentences the old substring router got wrong (see notes in the commit message).
@pytest.mark.parametrize("text", [
    "What is the first step to apply for a new connection?",   # 'fir' in first
    "Please confirm the office timings",                       # 'fir' in confirm
    "Is there a fire safety rule for meters?",                 # 'fir' in fire
    "Thank you for your courtesy",                             # 'court' in courtesy
    "Can I get the summary of tariff plans?",                  # 'my' in summary
    "Why is the status of the power outage unknown in my area?",  # bare 'status'
    "Which account types do you offer for commercial users?",  # bare 'account'
])
def test_old_substring_false_positives_are_gone(rules, text):
    assert label(rules, text) == "general"


@pytest.mark.parametrize("text,expected", [
    ("mera bill kitna hai", "personalized"),
    ("बिजली का बिल कितना आया है", "personalized"),
    ("I will take this to the consumer forum", "heavy_llm"),
    ("I want compensation for the damaged appliances", "heavy_llm"),
    ("I'm going to file an FIR against your staff", "heavy_llm"),
    ("আমার বিলটা ভুল এসেছে", "personalized"),
])
def test_old_substring_false_negatives_are_fixed(rules, text, expected):
    assert label(rules, text) == expected


def test_latin_terms_match_whole_words_only(rules):
    assert label(rules, "file an FIR") == "heavy_llm"
    assert label(rules, "first confirm fire") == "general"


def test_indic_terms_match_inflected_forms(rules):
    # বিল -> বিলটা / বিলের, মিটার -> মিটারের
    assert label(rules, "আমার বিলটা দেখান") == "personalized"
    assert label(rules, "আমার বিলের অঙ্ক কত") == "personalized"
    assert label(rules, "আমার মিটারের রিডিং ভুল") == "personalized"


def test_indic_words_are_not_split_at_vowel_signs():
    # Combining marks must stay inside the word.
    assert tokenize("বিলের হিসাব") == ["বিলের", "হিসাব"]
    assert tokenize("बिजली का बिल।") == ["बिजली", "का", "बिल"]


def test_phrases_require_consecutive_words(rules):
    assert label(rules, "what is my meter number") == "personalized"
    # 'meter' and 'number' apart, no possessive: not the phrase
    assert label(rules, "the number of meter readers") == "general"


def test_personal_wins_over_escalation(rules):
    # Current behavior, documented: both fire, personal is checked first.
    assert label(rules, "I will go to court over my bill") == "personalized"


def test_router_uses_rules_and_keeps_existing_behavior():
    catalog = IntentCatalog(yaml_path="data/intents.yaml")
    cache = SemanticCache(threshold=0.80)
    catalog.populate_semantic_cache(cache)
    router = Router(catalog, cache)

    assert router.route("What is the first step to apply?", lang="hi-en").decision != "heavy_llm"
    assert router.route("I will take this to the consumer forum", lang="hi-en").decision == "heavy_llm"
    assert router.route("What is my bill this month?", lang="hi-en").decision == "personalized"


def test_missing_rules_file_fails_loudly(tmp_path):
    with pytest.raises(FileNotFoundError):
        RoutingRules.load(str(tmp_path / "nope.yaml"))


def test_yaml_boolean_trap_is_rejected():
    raw = {
        "personal": {"phrases": ["meter number"], "possessives": [True], "account_terms": ["bill"]},
        "escalation": {"terms": ["court"]},
    }
    with pytest.raises(ValueError):
        RoutingRules.from_dict(raw)


def test_eval_set_regression_floor(rules):
    """Guards against rule edits that make routing worse on the labeled set.

    Floors sit slightly below the current scores. Raise them when the rules improve.
    """
    rows = [json.loads(l) for l in open(REPO_ROOT / "data" / "router_eval.jsonl", encoding="utf-8") if l.strip()]
    correct = sum(label(rules, r["text"]) == r["expected"] for r in rows)
    assert correct / len(rows) >= 0.90

    personal = [r for r in rows if r["expected"] == "personalized"]
    assert sum(label(rules, r["text"]) == "personalized" for r in personal) / len(personal) >= 0.95

    predicted_heavy = [r for r in rows if label(rules, r["text"]) == "heavy_llm"]
    assert sum(r["expected"] == "heavy_llm" for r in predicted_heavy) / len(predicted_heavy) >= 0.90