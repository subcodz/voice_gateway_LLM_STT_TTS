"""Enterprise intent loader and registry manager.

Why this module exists:
Parses `data/intents.yaml` into structured Python models. It ensures that personal
information (such as meter-specific bill queries or private complaint tickets) is flagged
as personal=True, strictly preventing it from ever being served from the semantic cache.
"""

import os
from typing import Dict, List, Optional
import yaml
from pydantic import BaseModel, Field

from app.cache.semantic import SemanticCache


class LanguageIntentData(BaseModel):
    canonical_reply: str
    examples: List[str] = Field(default_factory=list)


class IntentItem(BaseModel):
    id: str
    personal: bool = False
    languages: Dict[str, LanguageIntentData] = Field(default_factory=dict)


class IntentCatalog:
    def __init__(self, yaml_path: str = "data/intents.yaml"):
        self.yaml_path = yaml_path
        self.intents: Dict[str, IntentItem] = {}
        self.load()

    def load(self):
        if not os.path.exists(self.yaml_path):
            return

        with open(self.yaml_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        if not raw or "intents" not in raw:
            return

        for item in raw["intents"]:
            intent = IntentItem(**item)
            self.intents[intent.id] = intent

    def is_personal(self, intent_id: str) -> bool:
        if intent_id in self.intents:
            return self.intents[intent_id].personal
        return False

    def populate_semantic_cache(self, cache: SemanticCache):
        """Populates the semantic response cache with non-personal, whitelisted intents."""
        for intent in self.intents.values():
            if intent.personal:
                continue
            for lang, data in intent.languages.items():
                cache.register_intent(
                    intent_id=intent.id,
                    language=lang,
                    canonical_reply=data.canonical_reply,
                    examples=data.examples,
                    is_personal=False,
                    is_whitelisted=True
                )
