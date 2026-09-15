import logging
import os
from datetime import date, datetime
from typing import List, Optional

from newscrawler.core.constants import (
    DBSCAN_EPS,
    DBSCAN_MIN_SAMPLES,
    DIGESTS_DIR,
    EMBEDDING_MODEL_HF,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    NEWSLETTER_CATEGORY_KEYWORDS,
    SOURCE_AUTHORITY,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_CATEGORY_EMOJIS = {
    "macroeconomics": "📊 Makroekonomi",
    "capital_market": "📈 Pasar Modal",
    "banking":        "🏦 Perbankan",
    "corporate":      "🏭 Korporasi",
    "commodities":    "🛢️ Komoditas",
    "other":          "📰 Berita Lainnya",
}

_SUMMARIZE_PROMPT = (
    "Buat rangkuman berita berikut dalam 3-5 poin dalam bahasa yang sama dengan artikel.\n"
    "Fokus pada: apa yang terjadi, siapa yang terlibat, angka-angka penting.\n"
    "Gunakan format bullet point dengan tanda '-'.\n\n"
    "Artikel:\n{articles}"
)


class NewsletterGenerator:
    def __init__(self, newsletter_datasource, api_key: str = None, model_name: str = None):
        self.ds         = newsletter_datasource
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

        # ── Cluster ──────────────────────────────────────────────────────────
        vectors        = self._encode([a["l1_text"] for a in articles])
        labels         = self._cluster(vectors)
        cluster_groups = self._group_by_label(articles, labels)

        # ── Build cluster summaries ───────────────────────────────────────────
        clusters = []
        for label, cluster_articles in sorted(cluster_groups.items()):
            if label == -1:
                continue  # noise → "Berita Lainnya"
            category  = self.assign_category(cluster_articles)
            headline  = self._pick_cluster_headline(cluster_articles)
            summary   = self.summarize_cluster(cluster_articles)
            sources   = self._unique_sources(cluster_articles)
            links     = self._top_links(cluster_articles)
            clusters.append({
                "label":    label,
                "category": category,
                "headline": headline,
                "summary":  summary,
                "sources":  sources,
                "links":    links,
                "articles": cluster_articles,
            })

        noise_articles = cluster_groups.get(-1, [])

        # ── Render markdown ───────────────────────────────────────────────────
        md_content = self._render_markdown(target_date, clusters, noise_articles, articles)

        # ── Write file ────────────────────────────────────────────────────────
        os.makedirs(DIGESTS_DIR, exist_ok=True)
        file_name = target_date.strftime("%Y-%m-%d.md")
        file_path = os.path.join(DIGESTS_DIR, file_name)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        logger.info(f"Digest written to {file_path}")

        # ── Save to DB ────────────────────────────────────────────────────────
        category_counts = {}
        for c in clusters:
            category_counts[c["category"]] = category_counts.get(c["category"], 0) + 1

        generation_ms = _now_ms() - start_ms
        self.ds.save_digest(
            digest_date=target_date,
            file_path=file_path,
            cluster_count=len(clusters),
            article_count=len(articles),
            categories=category_counts,
            source_ids=[a["sitemap_id"] for a in articles],
            generation_ms=generation_ms,
        )
        logger.info(f"Newsletter generated in {generation_ms}ms: "
                    f"{len(clusters)} clusters, {len(articles)} articles.")
        return file_path

    # ── Category assignment ──────────────────────────────────────────────────

    def assign_category(self, articles: list) -> str:
        combined = " ".join(
            (a.get("headline", "") + " " + a.get("l1_text", "")).lower()
            for a in articles
        )
        scores = {
            cat: sum(1 for kw in kws if kw in combined)
            for cat, kws in NEWSLETTER_CATEGORY_KEYWORDS.items()
        }
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "other"

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
        from sentence_transformers import SentenceTransformer
        if self._embedding_model is None:
            logger.info(f"Loading embedding model for newsletter: {EMBEDDING_MODEL_HF}")
            self._embedding_model = SentenceTransformer(EMBEDDING_MODEL_HF)
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

    def _render_markdown(self, target_date: date, clusters: list,
                          noise: list, all_articles: list) -> str:
        lines = []
        date_str = target_date.strftime("%-d %B %Y") if os.name != "nt" else \
                   target_date.strftime("%d %B %Y").lstrip("0")
        lines.append(f"# Rangkuman Berita — {date_str}")
        lines.append(f"\n> Dibuat otomatis dari 33 portal berita Indonesia | "
                     f"{datetime.now().strftime('%H:%M')} WIB\n")
        lines.append("---\n")

        # Group clusters by category
        by_category: dict = {}
        for c in clusters:
            by_category.setdefault(c["category"], []).append(c)

        for cat_key in ["macroeconomics", "capital_market", "banking",
                        "corporate", "commodities", "other"]:
            cat_clusters = by_category.get(cat_key, [])
            if not cat_clusters:
                continue
            lines.append(f"## {_CATEGORY_EMOJIS[cat_key]}\n")
            for cluster in cat_clusters:
                lines.append(f"### {cluster['headline']}\n")
                lines.append(cluster["summary"])
                lines.append("")
                sources_str = " · ".join(cluster["sources"])
                lines.append(f"**Sumber ({len(cluster['sources'])} portal):** {sources_str}")
                link_parts = [f"[{l['source']}, {date_str}]({l['link']})"
                              for l in cluster["links"]]
                if link_parts:
                    lines.append(f"**Artikel terkait:** {' · '.join(link_parts)}")
                lines.append("\n---\n")

        # Noise / singletons
        if noise:
            lines.append(f"## {_CATEGORY_EMOJIS['other']}\n")
            for a in noise:
                link = f"[{a['source']}, {date_str}]({a['link']})" if a.get("link") \
                       else a["source"]
                lines.append(f"- {a['headline']} — {link}")
            lines.append("\n---\n")

        cluster_count = len(clusters)
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
