import logging
import os
from datetime import date, datetime
from typing import Callable, List, Optional

from newscrawler.core.constants import (
    DBSCAN_EPS,
    DBSCAN_MIN_SAMPLES,
    DIGESTS_DIR,
    EMBEDDING_MODEL_HF,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    NEWSLETTER_MAX_CLUSTERS_PER_TOPIC,
    SOURCE_AUTHORITY,
)
from newscrawler.core.filter_rubric import TOPICS_FINANCE, TOPICS_NEWS

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# SYS-40 (#126): the digest is sectioned by articles.topic (SYS-37), in
# filter_rubric's order -- the five finance topics first, then the rest.
SECTION_ORDER: List[str] = TOPICS_FINANCE + TOPICS_NEWS
FALLBACK_TOPIC = "other_news"   # an article with no (or an unknown) topic
SECTION_TITLES = {
    "markets":             "📈 Pasar",
    "macro_policy":        "📊 Kebijakan & Makroekonomi",
    "corporate":           "🏭 Korporasi",
    "commodities_energy":  "🛢️ Komoditas & Energi",
    "consumer":            "🛒 Konsumen & Bisnis",
    "politics_government": "🏛️ Politik & Pemerintahan",
    "law_crime":           "⚖️ Hukum & Kriminal",
    "disaster_accident":   "🚨 Bencana & Kecelakaan",
    "international":       "🌏 Internasional",
    "tech_science":        "🔬 Teknologi & Sains",
    "health_education":    "🏥 Kesehatan & Pendidikan",
    "other_news":          "📰 Berita Lainnya",
}

_SUMMARIZE_PROMPT = (
    "Buat rangkuman berita berikut dalam 3-5 poin dalam bahasa yang sama dengan artikel.\n"
    "Fokus pada: apa yang terjadi, siapa yang terlibat, angka-angka penting.\n"
    "Gunakan format bullet point dengan tanda '-'.\n\n"
    "Artikel:\n{articles}"
)


class NewsletterGenerator:
    def __init__(self, newsletter_datasource, api_key: str = None, model_name: str = None,
                 embed_documents: Optional[Callable[[List[str]], List[List[float]]]] = None):
        """embed_documents: DBT-02 (#21) -- the pipeline passes the FAISS
        datasource's MiniLM (`embed_documents`, normalized, batch 64), so a
        newsletter run does not load a second copy of the same model. Without
        it the model is loaded here on first use (a standalone generator)."""
        self.ds         = newsletter_datasource
        self._embed_documents = embed_documents
        self.api_key    = api_key    or GEMINI_API_KEY
        self.model_name = model_name or GEMINI_MODEL

        if self.api_key:
            from google import genai
            # Initialize the client instead of using a global configuration.
            # (If you set GEMINI_API_KEY as an environment var, you can just use genai.Client())
            self._client = genai.Client(api_key=self.api_key)
        else:
            logger.warning("GEMINI_API_KEY not set — summaries will use headlines only.")
            self._client = None

        # Lazy-load embedding model (same as pipeline)
        self._embedding_model = None

    # ── Public entry point ───────────────────────────────────────────────────

    def generate(self, target_date: date = None) -> Optional[str]:
        start_ms = _now_ms()
        if target_date is None:
            target_date = date.today()

        date_int = int(target_date.strftime("%Y%m%d"))
        logger.info(f"Generating newsletter for {target_date} (date_int={date_int})")

        articles = self.ds.get_articles_for_date(date_int)
        if not articles:
            logger.warning(f"No articles found for {target_date}. Generating empty digest.")
            return self._write_empty_digest(target_date, start_ms)

        logger.info(f"Loaded {len(articles)} articles for clustering.")

        # SYS-40: one encode for the day, then DBSCAN within each topic, so a big
        # political story cannot absorb the economy items next to it.
        vectors = self._encode([a["l1_text"] for a in articles])
        sections = self.build_sections(articles, vectors)

        # Summaries only for the clusters that are shown.
        for section in sections:
            for cluster in section["clusters"]:
                cluster["summary"] = self.summarize_cluster(cluster["articles"])

        md_content = self._render_markdown(target_date, sections, articles)

        os.makedirs(DIGESTS_DIR, exist_ok=True)
        file_name = target_date.strftime("%Y-%m-%d.md")
        file_path = os.path.join(DIGESTS_DIR, file_name)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        logger.info(f"Digest written to {file_path}")

        # SYS-40: the digest's composition per topic, queryable from the row.
        composition = {
            sec["topic"]: {"articles": sec["article_count"], "clusters": sec["cluster_count"],
                           "shown": len(sec["clusters"])}
            for sec in sections
        }
        cluster_count = sum(sec["cluster_count"] for sec in sections)
        generation_ms = _now_ms() - start_ms
        self.ds.save_digest(
            digest_date=target_date,
            file_path=file_path,
            cluster_count=cluster_count,
            article_count=len(articles),
            categories=composition,
            source_ids=[a["sitemap_id"] for a in articles],
            generation_ms=generation_ms,
        )
        logger.info(f"Newsletter generated in {generation_ms}ms: "
                    f"{cluster_count} clusters in {len(sections)} sections, {len(articles)} articles.")
        return file_path

    # ── Sections ──

    @staticmethod
    def topic_of(article: dict) -> str:
        topic = article.get("topic")
        return topic if topic in SECTION_TITLES else FALLBACK_TOPIC

    def build_sections(self, articles: list, vectors) -> List[dict]:
        """SYS-40: [{topic, article_count, cluster_count, clusters, more}] in
        SECTION_ORDER, empty topics omitted. `clusters` are the shown ones,
        ranked by size x distinct sources, at most
        NEWSLETTER_MAX_CLUSTERS_PER_TOPIC; `more` counts the stories not shown
        (the clusters past the cap plus the unclustered articles)."""
        by_topic: dict = {}
        for i, a in enumerate(articles):
            by_topic.setdefault(self.topic_of(a), []).append(i)
        sections = []
        for topic in SECTION_ORDER:
            idx = by_topic.get(topic)
            if not idx:
                continue
            members = [articles[i] for i in idx]
            if len(idx) >= DBSCAN_MIN_SAMPLES:
                labels = self._cluster([vectors[i] for i in idx])
            else:
                labels = [-1] * len(idx)
            groups = self._group_by_label(members, labels)
            clusters = [self._describe_cluster(group) for label, group in groups.items() if label != -1]
            clusters.sort(key=lambda c: (len(c["articles"]) * len(c["sources"]), len(c["articles"])), reverse=True)
            shown = clusters[:NEWSLETTER_MAX_CLUSTERS_PER_TOPIC]
            sections.append({
                "topic": topic,
                "article_count": len(members),
                "cluster_count": len(clusters),
                "clusters": shown,
                "more": len(clusters) - len(shown) + len(groups.get(-1, [])),
            })
        return sections

    def _describe_cluster(self, cluster_articles: list) -> dict:
        return {
            "headline": self._pick_cluster_headline(cluster_articles),
            "sources":  self._unique_sources(cluster_articles),
            "links":    self._top_links(cluster_articles),
            "articles": cluster_articles,
        }

    # ── Cluster summarization ────────────────────────────────────────────────

    def summarize_cluster(self, articles: list) -> str:
        top3 = sorted(
            articles,
            key=lambda a: SOURCE_AUTHORITY.get(a["source"].upper(), 0.5),
            reverse=True,
        )[:3]

        if not self._client:
            return "\n".join(f"- {a['headline']}" for a in top3)

        article_texts = "\n\n".join(
            f"[{a['source']}] {a['headline']}\n{a['l1_text'][:500]}"
            for a in top3
        )
        prompt = _SUMMARIZE_PROMPT.format(articles=article_texts)
        try:
            resp = self._client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            return resp.text.strip()
        except Exception as e:
            logger.warning(f"Gemini summarization failed: {e}. Using headlines.")
            return "\n".join(f"- {a['headline']}" for a in top3)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _encode(self, texts: List[str]):
        if self._embed_documents is not None:
            import numpy as np
            return np.asarray(self._embed_documents(texts))
        from sentence_transformers import SentenceTransformer
        if self._embedding_model is None:
            logger.info(f"Loading embedding model for newsletter: {EMBEDDING_MODEL_HF}")
            from newscrawler.core.utils.hf_cache import resolve_model
            self._embedding_model = SentenceTransformer(resolve_model(EMBEDDING_MODEL_HF))
        return self._embedding_model.encode(
            texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False
        )

    def _cluster(self, vectors) -> list:
        from sklearn.cluster import DBSCAN
        labels = DBSCAN(
            eps=DBSCAN_EPS,
            min_samples=DBSCAN_MIN_SAMPLES,
            metric="cosine",
        ).fit(vectors).labels_
        return labels.tolist()

    @staticmethod
    def _group_by_label(articles: list, labels: list) -> dict:
        groups: dict = {}
        for article, label in zip(articles, labels):
            groups.setdefault(label, []).append(article)
        return groups

    @staticmethod
    def _pick_cluster_headline(articles: list) -> str:
        top = max(
            articles,
            key=lambda a: SOURCE_AUTHORITY.get(a["source"].upper(), 0.5),
        )
        return top["headline"]

    @staticmethod
    def _unique_sources(articles: list) -> List[str]:
        seen, out = set(), []
        for a in articles:
            s = a["source"].upper()
            if s not in seen:
                seen.add(s)
                out.append(a["source"])
        return out

    @staticmethod
    def _top_links(articles: list) -> List[dict]:
        sorted_arts = sorted(
            articles,
            key=lambda a: SOURCE_AUTHORITY.get(a["source"].upper(), 0.5),
            reverse=True,
        )[:3]
        return [{"source": a["source"], "link": a["link"], "headline": a["headline"]}
                for a in sorted_arts if a.get("link")]

    def _render_markdown(self, target_date: date, sections: list, all_articles: list) -> str:
        lines = []
        date_str = target_date.strftime("%-d %B %Y") if os.name != "nt" else \
                   target_date.strftime("%d %B %Y").lstrip("0")
        lines.append(f"# Rangkuman Berita — {date_str}")
        lines.append(f"\n> Dibuat otomatis dari portal berita Indonesia | "
                     f"{datetime.now().strftime('%H:%M')} WIB\n")
        lines.append("---\n")

        for section in sections:
            lines.append(f"## {SECTION_TITLES[section['topic']]}\n")
            for cluster in section["clusters"]:
                lines.append(f"### {cluster['headline']}\n")
                lines.append(cluster.get("summary") or "")
                lines.append("")
                sources_str = " · ".join(cluster["sources"])
                lines.append(f"**Sumber ({len(cluster['sources'])} portal):** {sources_str}")
                link_parts = [f"[{l['source']}, {date_str}]({l['link']})"
                              for l in cluster["links"]]
                if link_parts:
                    lines.append(f"**Artikel terkait:** {' · '.join(link_parts)}")
                lines.append("")
            if section["more"]:
                lines.append(f"*…dan {section['more']} berita lainnya di bagian ini.*")
            lines.append("\n---\n")

        cluster_count = sum(sec["cluster_count"] for sec in sections)
        lines.append(
            f"*Total artikel hari ini: {len(all_articles)} | "
            f"Cluster teridentifikasi: {cluster_count} | "
            f"Dihasilkan: {datetime.now().strftime('%H:%M')} WIB*"
        )
        return "\n".join(lines) + "\n"

    def _write_empty_digest(self, target_date: date, start_ms: int) -> Optional[str]:
        os.makedirs(DIGESTS_DIR, exist_ok=True)
        file_name = target_date.strftime("%Y-%m-%d.md")
        file_path = os.path.join(DIGESTS_DIR, file_name)
        date_str  = target_date.isoformat()
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"# Rangkuman Berita — {date_str}\n\n"
                    f"> Tidak ada artikel hari ini.\n")
        generation_ms = _now_ms() - start_ms
        self.ds.save_digest(
            digest_date=target_date, file_path=file_path,
            cluster_count=0, article_count=0, categories={},
            source_ids=[], generation_ms=generation_ms,
        )
        return file_path


def _now_ms() -> int:
    return int(datetime.utcnow().timestamp() * 1000)
