"""Rule-based routing signals: personal-data guardrail and escalation detection.

Why this module exists:
The router needs a cheap, auditable, fail-closed check for two things that must
never depend on a fuzzy model: (1) queries about the caller's own account, which
must never be answered from a shared cache, and (2) escalation language (legal
threats, compensation demands) that should reach the heavy LLM tier.

The original implementation used raw substring checks, so a rule like "fir"
(First Information Report) also fired on "first", "confirm" and "fire". This
module replaces that with word-aware matching and moves all vocabulary into
data/routing_rules.yaml so it can be extended without touching code.

Matching rules:
- Text is NFKC-normalized, lowercased and split into words. Letters, combining
  marks (Indic vowel signs, viramas) and digits count as word characters, so
  Bengali and Devanagari words are never cut in the middle.
- Latin-script terms must match a whole word ("fir" does not match "first").
- Indic-script terms match as word prefixes with a short allowed ending, so
  inflections still hit (বিল matches বিলের and বিলটা).
- Multi-word terms ("meter number") match consecutive words in order.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml

# repo_root/data/routing_rules.yaml (this file lives in backend/app/routing/)
DEFAULT_RULES_PATH = Path(__file__).resolve().parents[3] / "data" / "routing_rules.yaml"

# How many extra characters an Indic word may carry beyond the rule term
# (case endings and plural markers such as -ের, -টা, -গুলো).
_MAX_INDIC_SUFFIX = 4


def _is_word_char(ch: str) -> bool:
    if ch in ("\u200c", "\u200d"):  # ZWNJ / ZWJ occur inside Indic words
        return True
    return unicodedata.category(ch)[0] in ("L", "M", "N")


def _is_indic(token: str) -> bool:
    return any(0x0900 <= ord(c) <= 0x0DFF for c in token)


def tokenize(text: str) -> List[str]:
    """Splits text into lowercase words, keeping Indic words intact."""
    normalized = unicodedata.normalize("NFKC", text).lower()
    tokens: List[str] = []
    buf: List[str] = []
    for ch in normalized:
        if _is_word_char(ch):
            buf.append(ch)
        elif buf:
            tokens.append("".join(buf))
            buf = []
    if buf:
        tokens.append("".join(buf))
    return tokens


@dataclass(frozen=True)
class Term:
    """One rule entry: a single word or a multi-word phrase."""

    raw: str
    tokens: Tuple[str, ...]
    indic: Tuple[bool, ...]

    @classmethod
    def parse(cls, raw: str) -> "Term":
        tokens = tuple(tokenize(raw))
        if not tokens:
            raise ValueError(f"Routing rule term has no usable words: {raw!r}")
        return cls(raw=raw, tokens=tokens, indic=tuple(_is_indic(t) for t in tokens))

    def _matches_at(self, words: Sequence[str], start: int) -> bool:
        for offset, (rule_tok, indic) in enumerate(zip(self.tokens, self.indic)):
            word = words[start + offset]
            if indic:
                if not word.startswith(rule_tok):
                    return False
                if len(word) - len(rule_tok) > _MAX_INDIC_SUFFIX:
                    return False
            elif word != rule_tok:
                return False
        return True

    def found_in(self, words: Sequence[str]) -> bool:
        last_start = len(words) - len(self.tokens)
        return any(self._matches_at(words, i) for i in range(last_start + 1))


@dataclass(frozen=True)
class RuleHit:
    label: str  # "personalized" or "heavy_llm"
    reason: str
    matched: str


def _load_terms(raw: Dict[str, Any], section: str, key: str) -> List[Term]:
    block = raw.get(section)
    if not isinstance(block, dict) or key not in block:
        raise ValueError(f"routing rules: missing '{section}.{key}'")
    items = block[key]
    if not isinstance(items, list) or not items:
        raise ValueError(f"routing rules: '{section}.{key}' must be a non-empty list")
    terms: List[Term] = []
    for item in items:
        if not isinstance(item, str):
            # Catches YAML surprises such as bare no/yes/on/off becoming booleans.
            raise ValueError(
                f"routing rules: '{section}.{key}' has a non-string entry {item!r}; quote it"
            )
        terms.append(Term.parse(item))
    return terms


class RoutingRules:
    def __init__(
        self,
        personal_phrases: List[Term],
        possessives: List[Term],
        account_terms: List[Term],
        escalation_terms: List[Term],
    ):
        self.personal_phrases = personal_phrases
        self.possessives = possessives
        self.account_terms = account_terms
        self.escalation_terms = escalation_terms

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "RoutingRules":
        return cls(
            personal_phrases=_load_terms(raw, "personal", "phrases"),
            possessives=_load_terms(raw, "personal", "possessives"),
            account_terms=_load_terms(raw, "personal", "account_terms"),
            escalation_terms=_load_terms(raw, "escalation", "terms"),
        )

    @classmethod
    def load(cls, path: Optional[str] = None) -> "RoutingRules":
        """Loads rules from YAML. Fails loudly: a silently empty rule set would
        disable the personal-data guardrail without anyone noticing."""
        rules_path = Path(path) if path else DEFAULT_RULES_PATH
        if not rules_path.exists():
            raise FileNotFoundError(f"Routing rules file not found: {rules_path}")
        with open(rules_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        if not isinstance(raw, dict):
            raise ValueError(f"Routing rules file is empty or malformed: {rules_path}")
        return cls.from_dict(raw)

    @staticmethod
    def _first_match(terms: List[Term], words: Sequence[str]) -> Optional[Term]:
        for term in terms:
            if term.found_in(words):
                return term
        return None

    def classify(self, text: str) -> Optional[RuleHit]:
        """Returns a hit for personal or escalation language, else None.

        Personal is checked first so account-specific queries can never reach
        the shared cache, even if they also contain escalation language.
        """
        words = tokenize(text)
        if not words:
            return None

        phrase = self._first_match(self.personal_phrases, words)
        if phrase:
            return RuleHit("personalized", f"Detected personal phrase '{phrase.raw}'", phrase.raw)

        possessive = self._first_match(self.possessives, words)
        if possessive:
            account = self._first_match(self.account_terms, words)
            if account:
                return RuleHit(
                    "personalized",
                    f"Detected possessive '{possessive.raw}' with account term '{account.raw}'",
                    f"{possessive.raw}+{account.raw}",
                )

        escalation = self._first_match(self.escalation_terms, words)
        if escalation:
            return RuleHit(
                "heavy_llm", f"Detected escalation term '{escalation.raw}'", escalation.raw
            )

        return None