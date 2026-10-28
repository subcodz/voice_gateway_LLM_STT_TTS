"""Tests for routing decisions, personal intent protection, and clause splitting."""

import pytest
from app.cache.semantic import SemanticCache
from app.routing.intents import IntentCatalog
from app.routing.router import Router
from app.routing.splitter import split_into_clauses


def test_clause_splitter_indic_and_english():
    text = "আপনার বিদ্যুৎ বিল তৈরি হয়েছে। দয়া করে ১৫ তারিখের মধ্যে দিন! ধন্যবাদ।"
    clauses = split_into_clauses(text)
    assert len(clauses) == 3
    assert "আপনার বিদ্যুৎ বিল তৈরি হয়েছে।" in clauses
    assert "দয়া করে ১৫ তারিখের মধ্যে দিন!" in clauses
    assert "ধন্যবাদ।" in clauses


def test_personal_intent_never_semantic_cached():
    catalog = IntentCatalog(yaml_path="data/intents.yaml")
    cache = SemanticCache(threshold=0.80)
    catalog.populate_semantic_cache(cache)

    router = Router(catalog, cache)

    # 1. Personal inquiry with specific account / bill question
    personal_query = "আমার চলতি মাসের বিদ্যুৎ বিল কত এসেছে?"
    decision = router.route(personal_query, lang="bn-IN")
    assert decision.decision == "personalized"
    assert decision.canonical_reply is None  # Must never return cached canonical reply!

    # 2. Public non-personal outage FAQ
    faq_query = "আমাদের এখানে বিদ্যুৎ চলে গেছে কখন আসবে?"
    faq_decision = router.route(faq_query, lang="bn-IN")
    assert faq_decision.decision == "cached_intent"
    assert faq_decision.intent_id == "power_outage"
    assert faq_decision.canonical_reply is not None


def test_escalation_triggers_heavy_tier():
    catalog = IntentCatalog(yaml_path="data/intents.yaml")
    cache = SemanticCache(threshold=0.80)
    router = Router(catalog, cache)

    escalation_query = "আমি এই বিল নিয়ে আদালতে যাব এবং legal dispute করব।"
    decision = router.route(escalation_query, lang="bn-IN")
    assert decision.decision == "heavy_llm"
