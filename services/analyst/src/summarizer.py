"""Map-reduce summarizer using Ollama."""

import httpx
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class MapReduceSummarizer:
    """Summarizes clusters of related articles using map-reduce approach."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b-instruct",
        timeout: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def _generate(self, prompt: str) -> str:
        """Generate text using Ollama."""
        try:
            response = self.client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.3},
                },
            )
            response.raise_for_status()
            return response.json().get("response", "")
        except Exception as e:
            logger.error(f"Generation error: {e}")
            return ""

    def summarize_article(self, headline: str, text: str) -> str:
        """Summarize a single article."""
        prompt = f"""Ringkas berita berikut dalam 2-3 kalimat dalam Bahasa Indonesia:

Judul: {headline}
Isi: {text[:1500]}

Ringkasan:"""
        return self._generate(prompt)

    def combine_summaries(self, summaries: List[str], headlines: List[str]) -> str:
        """Combine multiple summaries into one comprehensive summary."""
        combined = "\n\n".join(
            f"- {h}: {s}" for h, s in zip(headlines, summaries) if s
        )

        prompt = f"""Berikut adalah ringkasan dari beberapa berita terkait:

{combined}

Buat satu ringkasan komprehensif yang menggabungkan semua informasi penting dalam 4-6 kalimat. Identifikasi tema utama dan poin-poin kunci:"""

        return self._generate(prompt)

    def summarize_cluster(self, articles: List[Dict]) -> str:
        """
        Map-reduce summarization of article cluster.

        Args:
            articles: List of article dicts with 'headline' and 'text' keys

        Returns:
            Combined summary
        """
        if not articles:
            return ""

        # MAP: Summarize each article
        summaries = []
        headlines = []

        for article in articles[:5]:  # Limit to 5 articles
            headline = article.get("metadata", {}).get("headline", "")
            text = article.get("text", "")

            if headline or text:
                summary = self.summarize_article(headline, text)
                if summary:
                    summaries.append(summary)
                    headlines.append(headline)

        if not summaries:
            return ""

        # REDUCE: Combine summaries
        if len(summaries) == 1:
            return summaries[0]

        return self.combine_summaries(summaries, headlines)

    def is_available(self) -> bool:
        try:
            response = self.client.get(f"{self.base_url}/api/tags")
            return response.status_code == 200
        except Exception:
            return False

    def close(self):
        if self._client:
            self._client.close()
            self._client = None
