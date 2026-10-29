"""Query routing engine for cached intent vs LLM tier decisions.

Why this module exists:
Analyzes the caller's transcript to determine the optimal execution path.
If an utterance matches a known non-personal FAQ above the semantic threshold,
it routes to 'cached_intent' (saving LLM latency and cost). Queries containing private
or personalized indicators are routed to 'personalized' (enforcing live LLM generation
without caching), and complex escalations route to the 'heavy_llm' tier.
"""

from typing import Optional
from pydantic import BaseModel

from app.cache.semantic import SemanticCache
from app.routing.intents import IntentCatalog


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


# Key phrases indicating personalized, account-specific inquiries
PERSONAL_KEYWORDS = [
    "আমার বিল", "আমার বকেয়া", "मेरा बिल", "बकाया बिल", "my bill",
    "মিটার নম্বর", "मीटर नंबर", "meter number", "অভিযোগ নম্বর",
    "शिकायत संख्या", "complaint number", "status", "স্ট্যাটাস", "खाता", "account",
    "বিল কত", "কত বিল", "কত টাকা বিল", "বকেয়া কত", "লাস্ট ডেট", "last date", "due date",
    "অভিযোগের কি", "কমপ্লেন এর", "কি হলো আমার"
]

# Possessive pronouns that indicate personal context when combined with bill/complaint/meter
POSSESSIVES = ["আমার", "আমার", "मेरा", "मेरी", "मेरे", "my", "amar"]
ACCOUNT_TERMS = ["বিল", "বকেয়া", "মিটার", "কমপ্লেন", "অভিযোগ", "বিল", "bill", "meter", "complaint", "due"]

# Phrases indicating escalation / heavy reasoning
ESCALATION_KEYWORDS = [
    "আদালত", "পুলিশ", "legal", "dispute", "court", "ক্ষতিপূরণ",
    "मुआवजा", "विवाद", "fir", "threat"
]


class Router:
    def __init__(self, catalog: IntentCatalog, semantic_cache: SemanticCache):
        self.catalog = catalog
        self.semantic_cache = semantic_cache

    def route(self, text: str, lang: str = "bn-IN") -> RouteDecision:
        """Determines the routing path for an incoming query."""
        clean_text = text.strip()
        lower_text = clean_text.lower()
        effective_lang = detect_language(clean_text, fallback=lang)

        # 1. Check for personal account-specific queries (never semantic-cached)
        for kw in PERSONAL_KEYWORDS:
            if kw.lower() in lower_text:
                return RouteDecision(
                    decision="personalized",
                    sim_score=0.0,
                    reason=f"Detected personal keyword '{kw}'"
                )

        # Check combination of possessive pronoun + account term
        has_possessive = any(p in lower_text for p in POSSESSIVES)
        has_account_term = any(a in lower_text for a in ACCOUNT_TERMS)
        if has_possessive and has_account_term:
            return RouteDecision(
                decision="personalized",
                sim_score=0.0,
                reason="Detected personal possessive query on account/bill/meter"
            )

        # 2. Check for legal or dispute escalation (routes to heavy LLM)
        for kw in ESCALATION_KEYWORDS:
            if kw.lower() in lower_text:
                return RouteDecision(
                    decision="heavy_llm",
                    sim_score=0.0,
                    reason=f"Detected escalation keyword '{kw}'"
                )

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
