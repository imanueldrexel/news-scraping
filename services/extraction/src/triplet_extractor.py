"""Triplet extractor using Ollama LLM."""

import httpx
import json
import logging
import re
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from src.prompts.indonesian_triplet import (
    TRIPLET_EXTRACTION_PROMPT,
    TRIPLET_EXTRACTION_PROMPT_SHORT,
    ENTITY_TYPES,
    RELATION_TYPES,
)

logger = logging.getLogger(__name__)


@dataclass
class ExtractedTriplet:
    """An extracted triplet."""

    subject: str
    subject_type: str
    predicate: str
    object: str
    object_type: str
    confidence: float
    source_chunk_id: int = 0


class TripletExtractor:
    """
    Extracts knowledge graph triplets from Indonesian text using Ollama.
    Uses qwen2.5:7b-instruct for best Indonesian language support.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b-instruct",
        timeout: float = 120.0,
        min_confidence: float = 0.5,
    ):
        """
        Initialize triplet extractor.

        Args:
            base_url: Ollama API base URL
            model: LLM model name
            timeout: Request timeout in seconds
            min_confidence: Minimum confidence threshold
        """
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.min_confidence = min_confidence
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        """Lazy initialize HTTP client."""
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def extract(self, text: str, chunk_id: int = 0) -> List[ExtractedTriplet]:
        """
        Extract triplets from text.

        Args:
            text: Text to extract from
            chunk_id: Chunk identifier for tracking

        Returns:
            List of ExtractedTriplet objects
        """
        if not text or len(text) < 50:
            return []

        # Choose prompt based on text length
        if len(text) < 500:
            prompt = TRIPLET_EXTRACTION_PROMPT_SHORT.format(text=text)
        else:
            prompt = TRIPLET_EXTRACTION_PROMPT.format(text=text[:2000])

        try:
            response = self.client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": 0.1,
                        "top_p": 0.9,
                    },
                },
            )
            response.raise_for_status()

            result = response.json()
            raw_output = result.get("response", "{}")

            # Parse and validate triplets
            triplets = self._parse_response(raw_output, chunk_id)
            return triplets

        except httpx.TimeoutException:
            logger.warning(f"Timeout extracting triplets from chunk {chunk_id}")
            return []
        except httpx.HTTPError as e:
            logger.error(f"HTTP error: {e}")
            return []
        except Exception as e:
            logger.error(f"Extraction error: {e}")
            return []

    def _parse_response(
        self, response: str, chunk_id: int
    ) -> List[ExtractedTriplet]:
        """Parse LLM response into triplets."""
        triplets = []

        try:
            # Try to extract JSON from response
            json_match = re.search(r"\{[\s\S]*\}", response)
            if not json_match:
                logger.warning("No JSON found in response")
                return []

            data = json.loads(json_match.group())

            # Handle both direct triplets list and nested structure
            triplet_list = data.get("triplets", [])
            if not isinstance(triplet_list, list):
                return []

            for t in triplet_list:
                try:
                    triplet = self._validate_triplet(t, chunk_id)
                    if triplet:
                        triplets.append(triplet)
                except Exception as e:
                    logger.debug(f"Invalid triplet: {e}")

        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error: {e}")
        except Exception as e:
            logger.warning(f"Parse error: {e}")

        return triplets

    def _validate_triplet(
        self, data: Dict[str, Any], chunk_id: int
    ) -> Optional[ExtractedTriplet]:
        """Validate and create a triplet from dict."""
        # Required fields
        subject = str(data.get("subject", "")).strip()
        subject_type = str(data.get("subject_type", "")).upper().strip()
        predicate = str(data.get("predicate", "")).upper().strip()
        obj = str(data.get("object", "")).strip()
        object_type = str(data.get("object_type", "")).upper().strip()
        confidence = float(data.get("confidence", 0.5))

        # Validate required fields
        if not subject or not obj or not predicate:
            return None

        # Validate entity types
        if subject_type not in ENTITY_TYPES:
            subject_type = self._infer_entity_type(subject)
        if object_type not in ENTITY_TYPES:
            object_type = self._infer_entity_type(obj)

        # Validate relation type
        if predicate not in RELATION_TYPES:
            predicate = self._map_relation(predicate)
            if not predicate:
                return None

        # Filter by confidence
        if confidence < self.min_confidence:
            return None

        return ExtractedTriplet(
            subject=subject,
            subject_type=subject_type,
            predicate=predicate,
            object=obj,
            object_type=object_type,
            confidence=confidence,
            source_chunk_id=chunk_id,
        )

    def _infer_entity_type(self, entity: str) -> str:
        """Infer entity type from name."""
        entity_lower = entity.lower()

        # Company indicators
        if any(
            ind in entity_lower
            for ind in ["pt ", "pt.", "tbk", "cv ", "cv.", "bank ", "group"]
        ):
            return "COMPANY"

        # Government indicators
        if any(
            ind in entity_lower
            for ind in [
                "kementerian",
                "menteri",
                "presiden",
                "gubernur",
                "bumn",
                "ojk",
                "bi ",
                "bank indonesia",
            ]
        ):
            return "GOVERNMENT"

        # Organization indicators
        if any(
            ind in entity_lower
            for ind in ["asosiasi", "perhimpunan", "ikatan", "organisasi"]
        ):
            return "ORGANIZATION"

        # Location indicators
        if any(
            ind in entity_lower
            for ind in ["indonesia", "jakarta", "surabaya", "bandung", "kota", "provinsi"]
        ):
            return "LOCATION"

        # Default to PERSON for names
        return "PERSON"

    def _map_relation(self, relation: str) -> Optional[str]:
        """Map Indonesian relation to standard type."""
        relation_lower = relation.lower()

        mapping = {
            "bekerja": "WORKS_FOR",
            "kerja": "WORKS_FOR",
            "memiliki": "OWNS",
            "dimiliki": "OWNED_BY",
            "punya": "OWNS",
            "investasi": "INVESTED_IN",
            "berinvestasi": "INVESTED_IN",
            "akuisisi": "ACQUIRED",
            "mengakuisisi": "ACQUIRED",
            "membeli": "ACQUIRED",
            "bermitra": "PARTNERED_WITH",
            "kerjasama": "PARTNERED_WITH",
            "bekerjasama": "PARTNERED_WITH",
            "ditunjuk": "APPOINTED_AS",
            "diangkat": "APPOINTED_AS",
            "menjabat": "WORKS_FOR",
            "mundur": "RESIGNED_FROM",
            "resign": "RESIGNED_FROM",
            "mengundurkan": "RESIGNED_FROM",
            "mengumumkan": "ANNOUNCED",
            "umumkan": "ANNOUNCED",
            "berlokasi": "LOCATED_IN",
            "berkantor": "HEADQUARTERED_IN",
            "memimpin": "LEADS",
            "pimpin": "LEADS",
        }

        for key, value in mapping.items():
            if key in relation_lower:
                return value

        return None

    def extract_from_chunks(
        self, chunks: List[Dict[str, Any]]
    ) -> List[ExtractedTriplet]:
        """
        Extract triplets from multiple chunks.

        Args:
            chunks: List of chunk dicts with 'text' and 'chunk_id'

        Returns:
            Aggregated list of triplets
        """
        all_triplets = []

        for chunk in chunks:
            text = chunk.get("text", "")
            chunk_id = chunk.get("chunk_id", 0)

            triplets = self.extract(text, chunk_id)
            all_triplets.extend(triplets)

        # Deduplicate similar triplets
        return self._deduplicate_triplets(all_triplets)

    def _deduplicate_triplets(
        self, triplets: List[ExtractedTriplet]
    ) -> List[ExtractedTriplet]:
        """Remove duplicate triplets, keeping highest confidence."""
        seen = {}

        for t in triplets:
            key = (
                t.subject.lower(),
                t.predicate,
                t.object.lower(),
            )
            if key not in seen or t.confidence > seen[key].confidence:
                seen[key] = t

        return list(seen.values())

    def is_available(self) -> bool:
        """Check if Ollama and model are available."""
        try:
            response = self.client.get(f"{self.base_url}/api/tags")
            if response.status_code != 200:
                return False

            models = response.json().get("models", [])
            model_names = [m.get("name", "") for m in models]

            return any(self.model in name for name in model_names)
        except Exception:
            return False

    def close(self):
        """Close HTTP client."""
        if self._client:
            self._client.close()
            self._client = None
