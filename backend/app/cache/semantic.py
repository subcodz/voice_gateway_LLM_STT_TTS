"""Semantic response cache using vector embeddings and cosine similarity.

Why this module exists:
Eliminates redundant LLM generation by matching repetitive caller inquiries to verified
canonical responses. Matches are strictly confined to whitelisted, non-personal enterprise
intents (such as general power outage notices or bill payment instructions) to ensure 100%
factual correctness and zero data contamination between callers.

Matching is a gate, not a single threshold. multilingual-e5-small compresses its scores
(unrelated romanized sentences often land at 0.8+), so an embedding score alone produces
false hits. A query must pass every check:
  1. top score >= threshold
  2. top score beats the runner-up intent by at least min_margin
  3. unless the score is very high (>= strong_threshold), the query must share at least one
     content word with that intent's example utterances (cheap lexical sanity check)
"""

import logging
import math
import os
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from app.routing.rules import tokenize

log = logging.getLogger("semantic")
MODEL_NAME = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-small")

# Function words that carry no topic. Used only for the lexical sanity check.
# Heuristic list: extend it as you meet new false hits.
STOPWORDS: FrozenSet[str] = frozenset("""
a an the is are was were be been am do does did to of in on at for from with by and or but if so as
my me i you your we our it its this that these those there here what how when where why which who
can could will would should shall please tell about
hai hain ho hoga hogi hoon tha thi the ka ke ki ko se mai mein me par pe aur ya kya kaise kab kahan
kyun kitna kitni kitne koi kuch yeh ye woh wo isme iska iski isko isse usme uska uski usko mera meri
mere apna apni aap tum hum
ami amar tumi apni apnar ta ti gulo ey ei oi kothay kobe keno kemon koto ache achhe hobe hoy jabe
और या का के की को से में पर है हैं था थी क्या कैसे कब कहाँ कितना कितनी यह वह मेरा मेरी मेरे
আমি আমার তুমি আপনি আপনার কি কী কেন কখন কোথায় কত কিভাবে এই ওই আছে হবে হয়
""".split())


def content_tokens(text: str) -> Set[str]:
    """Topic-bearing words of a text: tokenized, stopwords and 1-char tokens removed."""
    return {t for t in tokenize(text) if t not in STOPWORDS and len(t) > 1}


def _tokens_match(a: str, b: str) -> bool:
    """Equal, or one is a prefix of the other (>= 4 chars) to tolerate inflection."""
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    return len(short) >= 4 and long_.startswith(short)


def has_overlap(query_tokens: Set[str], vocab: Set[str]) -> bool:
    return any(_tokens_match(q, v) for q in query_tokens for v in vocab)


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Computes cosine similarity between two float vectors."""
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class SemanticEntry:
    def __init__(
        self,
        intent_id: str,
        language: str,
        canonical_reply: str,
        is_personal: bool = False,
        is_whitelisted: bool = True,
        examples: Optional[List[str]] = None,
        embeddings: Optional[List[List[float]]] = None,
        vocab: Optional[Set[str]] = None,
    ):
        self.intent_id = intent_id
        self.language = language
        self.canonical_reply = canonical_reply
        self.is_personal = is_personal
        self.is_whitelisted = is_whitelisted
        self.examples = examples or []
        self.embeddings = embeddings or []
        self.vocab = vocab or set()


class SemanticCache:
    def __init__(
        self,
        threshold: float = 0.82,
        min_margin: Optional[float] = None,
        strong_threshold: Optional[float] = None,
        lexical_guard: Optional[bool] = None,
    ):
        self.threshold = threshold
        self.min_margin = float(os.getenv("SEMANTIC_MARGIN", "0")) if min_margin is None else min_margin
        self.strong_threshold = (
            float(os.getenv("SEMANTIC_STRONG", "0.95")) if strong_threshold is None else strong_threshold
        )
        self.lexical_guard = (
            os.getenv("SEMANTIC_LEXICAL_GUARD", "1") in ("1", "true", "True")
            if lexical_guard is None else lexical_guard
        )
        # (intent_id, language) -> SemanticEntry
        self._entries: Dict[Tuple[str, str], SemanticEntry] = {}
        self._embedder = None
        # Debug record of the most recent lookup (what was rejected and why)
        self.last_decision: Optional[dict] = None

    def _get_embedder(self):
        """Lazy loader for sentence embedder (multilingual-e5-small or fallback)."""
        if self._embedder is not None:
            return self._embedder
        mode = os.getenv("EMBEDDER", "auto")   # auto | real | mock
        if mode == "mock":
            self._embedder = "mock"
            return self._embedder
        try:
            from sentence_transformers import SentenceTransformer
            self._embedder = SentenceTransformer(MODEL_NAME, device="cpu")
            log.info("Loaded embedder %s", MODEL_NAME)
        except Exception:
            if mode == "real":
                raise                      # fail loudly, never degrade silently
            log.exception("Real embedder failed to load, falling back to MOCK")
            self._embedder = "mock"
        return self._embedder

    @property
    def embedder_name(self) -> str:
        e = self._get_embedder()
        return "mock" if e == "mock" else MODEL_NAME

    def warmup(self) -> None:
        self.embed_text("warmup")

    def embed_text(self, text: str, is_query: bool = True) -> List[float]:
        """Generates normalized vector embedding with query: or passage: prefix."""
        prefix = "query: " if is_query else "passage: "
        prefixed_text = prefix + text.strip()
        embedder = self._get_embedder()

        if embedder != "mock" and hasattr(embedder, "encode"):
            raw_vec = embedder.encode(prefixed_text, normalize_embeddings=True)
            if hasattr(raw_vec, "tolist"):
                return raw_vec.tolist()
            return list(raw_vec)

        # Deterministic 64-dimensional feature vector for offline testing
        # Using md5 hash for cross-process determinism (unlike Python's randomized hash())
        import hashlib
        tokens = text.lower().split()
        dim = 64
        vec = [0.0] * dim
        for i, token in enumerate(tokens):
            h_int = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
            idx = h_int % dim
            vec[idx] += 1.0 / (i + 1.0)
            # Add character bigrams
            for c1, c2 in zip(token, token[1:]):
                bg_int = int(hashlib.md5((c1 + c2).encode("utf-8")).hexdigest(), 16)
                b_idx = bg_int % dim
                vec[b_idx] += 0.5

        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def register_intent(
        self,
        intent_id: str,
        language: str,
        canonical_reply: str,
        examples: List[str],
        is_personal: bool = False,
        is_whitelisted: bool = True
    ):
        """Registers an intent, pre-computing embeddings for all example utterances."""
        # Never index personalized responses in the semantic cache
        if is_personal or not is_whitelisted:
            return

        embeddings = [self.embed_text(ex, is_query=False) for ex in examples]
        vocab: Set[str] = set()
        for ex in examples:
            vocab |= content_tokens(ex)
        entry = SemanticEntry(
            intent_id=intent_id,
            language=language,
            canonical_reply=canonical_reply,
            is_personal=is_personal,
            is_whitelisted=is_whitelisted,
            examples=examples,
            embeddings=embeddings,
            vocab=vocab,
        )
        self._entries[(intent_id, language)] = entry

    def _verdict(self, top: float, second: float, qtoks: Set[str], entry: SemanticEntry) -> str:
        if top < self.threshold:
            return "below_threshold"
        if len(self._entries) > 1 and top - second < self.min_margin:
            return "low_margin"
        if self.lexical_guard and top < self.strong_threshold:
            if not qtoks:
                return "no_content_words"
            if not has_overlap(qtoks, entry.vocab):
                return "no_lexical_overlap"
        return "hit"

    def lookup(
        self,
        query: str,
        language: str
    ) -> Optional[Tuple[str, str, float]]:
        """Searches for a semantic match among non-personal, whitelisted intents.

        Returns (intent_id, canonical_reply, similarity_score) only if the query passes
        the threshold, margin and lexical checks; otherwise None. The reason for the most
        recent decision is kept in self.last_decision and logged.
        """
        self.last_decision = None
        if not query or not query.strip():
            return None

        qvec = self.embed_text(query, is_query=True)
        qtoks = content_tokens(query)

        ranked: List[Tuple[float, SemanticEntry]] = []
        for (_, lang), entry in self._entries.items():
            if lang.lower() != language.lower() or entry.is_personal or not entry.is_whitelisted:
                continue
            best = max((cosine_similarity(qvec, v) for v in entry.embeddings), default=-1.0)
            ranked.append((best, entry))
        if not ranked:
            return None

        ranked.sort(key=lambda r: r[0], reverse=True)
        top, entry = ranked[0]
        second = ranked[1][0] if len(ranked) > 1 else 0.0
        verdict = self._verdict(top, second, qtoks, entry)

        self.last_decision = {
            "intent": entry.intent_id, "top": round(top, 4), "second": round(second, 4),
            "margin": round(top - second, 4), "verdict": verdict,
        }
        log.info("intent lookup lang=%s query=%r top=%s %.3f second=%.3f -> %s",
                 language, query[:60], entry.intent_id, top, second, verdict)

        if verdict != "hit":
            return None
        return entry.intent_id, entry.canonical_reply, round(top, 4)