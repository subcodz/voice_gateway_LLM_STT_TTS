# scripts/check_guided_path.py
import sys; sys.path.insert(0, "backend")
from app.cache.semantic import SemanticCache
from app.routing.intents import IntentCatalog
from app.routing.router import Router

GUIDED = [
    "How can I pay the electricity bill online?",
    "What are the office hours?",
    "How can I pay the electricity bill online?",
    "What are the ways to pay the electricity bill online?",
    "What should I do about voltage fluctuation?",
]
cat = IntentCatalog("data/intents.yaml"); cache = SemanticCache(0.82)
cat.populate_semantic_cache(cache); r = Router(cat, cache)
for q in GUIDED:
    d = r.route(q, lang="hi-en")
    print(f"{d.decision:14} {q}")
    assert d.decision != "personalized", q