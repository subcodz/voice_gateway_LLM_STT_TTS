"""Query routing engine for cached intent vs LLM tier decisions.

Why this module exists:
Analyzes the caller's transcript to determine the optimal execution path.
If an utterance matches a known non-personal FAQ above the semantic threshold,
it routes to 'cached_intent' (saving LLM latency and cost). Queries containing private
or personalized indicators are routed to 'personalized' (enforcing live LLM generation
without caching), and complex escalations route to the 'heavy_llm' tier.

The personal / escalation vocabulary lives in data/routing_rules.yaml and is
matched by app.routing.rules (word-aware, script-aware), not by substring checks.
"""

from typing import Optional
from pydantic import BaseModel

from app.cache.semantic import SemanticCache
from app.routing.intents import IntentCatalog
from app.routing.rules import RoutingRules


class RouteDecision(BaseModel):
    decision: str  # 'cached_intent', 'fast_llm', 'heavy_llm', 'personalized'
    intent_id: Optional[str] = None
    canonical_reply: Optional[str] = None
    sim_score: float = 0.0
    reason: str = ""


def detect_language(text: str, fallback: str = "hi-IN") -> str:
    """Detects primary language from Unicode script ranges and romanized Latin patterns."""
    if not text or not text.strip():
        return fallback
    bengali = 0
    devanagari = 0
    latin = 0
    total = 0
    for ch in text:
        cp = ord(ch)
        if 0x0980 <= cp <= 0x09FF:
            bengali += 1
            total += 1
        elif 0x0900 <= cp <= 0x097F:
            devanagari += 1
            total += 1
        elif (0x0041 <= cp <= 0x005A) or (0x0061 <= cp <= 0x007A):
            latin += 1
            total += 1
    if total == 0:
        return fallback
    if bengali / total > 0.35:
        return "bn-IN"
    if devanagari / total > 0.35:
        return "hi-IN"
    if latin / total > 0.5:
        return "hi-en"
    return fallback


class Router:
    def __init__(
        self,
        catalog: IntentCatalog,
        semantic_cache: SemanticCache,
        rules: Optional[RoutingRules] = None,
    ):
        self.catalog = catalog
        self.semantic_cache = semantic_cache
        self.rules = rules if rules is not None else RoutingRules.load()

    def route(self, text: str, lang: str = "bn-IN") -> RouteDecision:
        """Determines the routing path for an incoming query."""
        clean_text = text.strip()
        effective_lang = detect_language(clean_text, fallback=lang)

        # 1 & 2. Personal account queries (never semantic-cached) and legal or
        # dispute escalation (heavy LLM). Personal is checked before escalation.
        hit = self.rules.classify(clean_text)
        if hit:
            return RouteDecision(decision=hit.label, sim_score=0.0, reason=hit.reason)

        # 3. Check Semantic Cache for whitelisted non-personal intent match
        match = self.semantic_cache.lookup(clean_text, effective_lang)
        if not match and effective_lang != lang:
            match = self.semantic_cache.lookup(clean_text, lang)
        if match:
            intent_id, canonical_reply, score = match
            # Verify intent is not personal in catalog
            if not self.catalog.is_personal(intent_id):
                return RouteDecision(
                    decision="cached_intent",
                    intent_id=intent_id,
                    canonical_reply=canonical_reply,
                    sim_score=score,
                    reason=f"Semantic cache hit on intent '{intent_id}' with score {score:.4f}"
                )

        # 4. Default to Fast LLM tier
        return RouteDecision(
            decision="fast_llm",
            sim_score=0.0,
            reason="No semantic cache match; routed to fast LLM tier"
        )