import re
from typing import Dict, Optional


class EntityNormalizer:
    def normalize(self, name: str) -> str:
        """Lowercase, strip punctuation (except hyphens), collapse whitespace."""
        name = name.lower()
        name = re.sub(r"[^\w\s-]", "", name)
        name = re.sub(r"\s+", " ", name)
        return name.strip()

    def resolve_alias(self, raw_name: str, alias_map: Dict[str, int]) -> Optional[int]:
        """Returns entity_id if the normalized form of raw_name is in alias_map."""
        return alias_map.get(self.normalize(raw_name))

    def extract_context_snippet(
        self, article_text: str, entity_name: str, window: int = 200
    ) -> Optional[str]:
        """Returns up to 2*window chars centred on the first occurrence of entity_name."""
        idx = article_text.lower().find(entity_name.lower())
        if idx == -1:
            return None
        start = max(0, idx - window)
        end   = min(len(article_text), idx + len(entity_name) + window)
        snippet = article_text[start:end].strip()
        return f"...{snippet}..." if start > 0 or end < len(article_text) else snippet
