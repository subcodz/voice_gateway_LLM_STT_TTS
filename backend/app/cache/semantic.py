"""Semantic response cache using vector embeddings and cosine similarity.

Why this module exists:
Eliminates redundant LLM generation by matching repetitive caller inquiries to verified
canonical responses. Matches are strictly confined to whitelisted, non-personal enterprise
intents (such as general power outage notices or bill payment instructions) to ensure 100%
factual correctness and zero data contamination between callers.
"""

import math
from typing import Dict, List, Optional, Tuple


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
        embeddings: Optional[List[List[float]]] = None
    ):
        self.intent_id = intent_id
        self.language = language
        self.canonical_reply = canonical_reply
        self.is_personal = is_personal
        self.is_whitelisted = is_whitelisted
        self.examples = examples or []
        self.embeddings = embeddings or []


class SemanticCache:
    def __init__(self, threshold: float = 0.82):
        self.threshold = threshold
        # (intent_id, language) -> SemanticEntry
        self._entries: Dict[Tuple[str, str], SemanticEntry] = {}
        self._embedder = None

    def _get_embedder(self):
        """Lazy loader for sentence embedder (multilingual-e5-small or fallback)."""
        if self._embedder is None:
            try:
                import importlib
                import importlib.util
                if importlib.util.find_spec("sentence_transformers") is not None:
                    st_mod = importlib.import_module("sentence_transformers")
                    transformer_cls = getattr(st_mod, "SentenceTransformer")
                    self._embedder = transformer_cls("intfloat/multilingual-e5-small")
                else:
                    self._embedder = "mock"
            except Exception:
                # Fast offline mock embedder for tests and lightweight environments
                self._embedder = "mock"
        return self._embedder

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
        entry = SemanticEntry(
            intent_id=intent_id,
            language=language,
            canonical_reply=canonical_reply,
            is_personal=is_personal,
            is_whitelisted=is_whitelisted,
            examples=examples,
            embeddings=embeddings
        )
        self._entries[(intent_id, language)] = entry

    def lookup(
        self,
        query: str,
        language: str
    ) -> Optional[Tuple[str, str, float]]:
        """Searches for a semantic match among non-personal, whitelisted intents.
        
        Returns (intent_id, canonical_reply, similarity_score) if above threshold,
        otherwise returns None.
        """
        if not query or not query.strip():
            return None

        query_vec = self.embed_text(query, is_query=True)
        best_match: Optional[Tuple[str, str, float]] = None
        best_score = -1.0

        for (intent_id, lang), entry in self._entries.items():
            if lang.lower() != language.lower() or entry.is_personal or not entry.is_whitelisted:
                continue

            for ex_vec in entry.embeddings:
                sim = cosine_similarity(query_vec, ex_vec)
                if sim > best_score:
                    best_score = sim
                    if sim >= self.threshold:
                        best_match = (intent_id, entry.canonical_reply, round(sim, 4))

        return best_match
