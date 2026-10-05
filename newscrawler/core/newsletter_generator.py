import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Callable, List, Optional, Tuple

from newscrawler.core import newsletter_copy as copy
from newscrawler.core import newsletter_edition, story_summary
from newscrawler.core.constants import (
    DIGESTS_DIR,
    EMBEDDING_MODEL_HF,
    NEWSLETTER_CLUSTER_DISTANCE,
    NEWSLETTER_MAX_CLUSTERS_PER_STORY,
    NEWSLETTER_MAX_CLUSTERS_PER_TOPIC,
    NEWSLETTER_MAX_CONSECUTIVE_SUMMARY_ERRORS,
    NEWSLETTER_MIN_CLUSTER_SIZE,
    NEWSLETTER_MIN_SUMMARY_SHARE,
    SOURCE_AUTHORITY,
)
from newscrawler.core.filter_rubric import TOPICS_FINANCE, TOPICS_NEWS
from newscrawler.core.story_grouping import group_clusters, pick_shown
from newscrawler.core.summarizer import QuotaExhausted, Summarizer, SummarizerError, build_summarizer

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# SYS-40 (#126): the digest is sectioned by articles.topic (SYS-37), in
# filter_rubric's order -- the five finance topics first, then the rest.
SECTION_ORDER: List[str] = TOPICS_FINANCE + TOPICS_NEWS
FALLBACK_TOPIC = "other_news"   # an article with no (or an unknown) topic
SUMMARIES_KEY = "_summaries"    # newsletter_digests.categories: summary counts, not a topic (SYS-68)
EDITION_KEY = "_edition"        # ... and the 5-minute edition's stats (SYS-83), not a topic either
SECTION_TITLES = copy.SECTION_TITLES   # SYS-84: the reader's strings live in newsletter_copy

_MAX_LINKS = 3           # "Artikel terkait" links per cluster
_LINK_LABEL_CHARS = 70   # headline characters in a link label

_FROM_CONFIG = object()   # "build the summarizer from the environment" (None means: none)

# SYS-68 (#216): why a digest has fewer real summaries than clusters.
_STOP_REASONS = {
    "no_provider": "tidak ada penyedia LLM yang dikonfigurasi",
    "quota":       "kuota harian habis",
    "errors":      "layanan gagal berulang",
}


@dataclass
class SummaryStats:
    """SYS-68 (#216): how many of the shown clusters got a real summary. The
    rest carry their top headlines, which is a different product -- the
    newsletter_digests row, the log and the operator's note must all say so
    (and, SYS-84, the reader's notice at the top of the digest).

    SYS-82 (#239): `first_try` is how many were accepted without a retry, and
    `rejections` counts every refused answer by reason (json / length / number),
    including the refusals a retry then repaired."""
    total: int = 0
    summarized: int = 0
    provider: Optional[str] = None
    stopped: Optional[str] = None      # a key of _STOP_REASONS once the calls stopped
    groups_ok: int = 0                 # SYS-67: sections whose clusters were grouped by story
    groups_failed: int = 0             # ... and those where the grouping failed (shown as ranked)
    first_try: int = 0
    rejections: dict = field(default_factory=lambda: {reason: 0 for reason in story_summary.REASONS})

    @property
    def fallback(self) -> int:
        return self.total - self.summarized

    @property
    def share(self) -> float:
        return self.summarized / self.total if self.total else 1.0

    def describe(self) -> str:
        """The operator's line (log, crawl_log note, Telegram): never the reader's document (SYS-84)."""
        line = f"Ringkasan AI: {self.summarized}/{self.total}"
        if self.provider:
            line += f" ({self.provider})"
        if self.fallback:
            reason = _STOP_REASONS.get(self.stopped, "sebagian ringkasan gagal")
            line += f" — {reason}; sisanya hanya daftar judul"
        if any(self.rejections.values()):
            line += " | ditolak " + ", ".join(f"{reason} {n}" for reason, n in self.rejections.items() if n)
        if self.groups_failed:
            line += f" | pengelompokan cerita gagal di {self.groups_failed} bagian"
        return line

    def as_dict(self) -> dict:
        return asdict(self)


class DigestPath(str):
    """The digest's path, carrying `note`: what a caller must tell the operator
    about a degraded digest (None when every summary is real), and `edition`:
    the 5-minute edition's path (SYS-83; None when it was not built). Behaves
    as the plain path everywhere else."""

    def __new__(cls, path: str, note: Optional[str] = None, edition: Optional[str] = None):
        obj = super().__new__(cls, path)
        obj.note = note
        obj.edition = edition
        return obj


class NewsletterGenerator:
    def __init__(self, newsletter_datasource,
                 embed_documents: Optional[Callable[[List[str]], List[List[float]]]] = None,
                 summarizer=_FROM_CONFIG, usage=None):
        """embed_documents: DBT-02 (#21) -- the pipeline passes the FAISS
        datasource's MiniLM (`embed_documents`, normalized, batch 64), so a
        newsletter run does not load a second copy of the same model. Without
        it the model is loaded here on first use (a standalone generator).

        summarizer: an object with `.name` and `.summarize(prompt)` (ADR-001).
        Left out, it is built from NEWSLETTER_LLM_PROVIDER / the API keys, its
        calls counted through `usage` (anything with increment_api_call_count);
        None means no summaries -- the digest lists headlines and says so."""
        self.ds = newsletter_datasource
        self._embed_documents = embed_documents
        if summarizer is _FROM_CONFIG:
            summarizer = build_summarizer(usage=usage)
        if summarizer is None:
            logger.warning("No summarizer configured (OPENAI_API_KEY / GEMINI_API_KEY) — "
                           "summaries will use headlines only.")
        self._summarizer: Optional[Summarizer] = summarizer

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

        # SYS-40: one encode for the day, then clustering within each topic, so a big
        # political story cannot absorb the economy items next to it.
        vectors = self._encode([a["l1_text"] for a in articles])
        sections = self.build_sections(articles, vectors)

        # Summaries only for the clusters that are shown.
        stats = self._summarize_sections(sections)
        note = self._summary_note(stats)

        md_content = self._render_markdown(target_date, sections, articles, stats)

        os.makedirs(DIGESTS_DIR, exist_ok=True)
        file_name = target_date.strftime("%Y-%m-%d.md")
        file_path = os.path.join(DIGESTS_DIR, file_name)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        logger.info(f"Digest written to {file_path}")

        # SYS-83: the 5-minute edition, a second file; the digest above is the archive.
        edition_stats, edition_file = self._write_edition(target_date, sections, articles, stats, file_path)
        if edition_file is None:
            missing = f"5-minute edition not built: {edition_stats.get('reason')}"
            logger.error(missing)
            note = f"{note}; {missing}" if note else missing

        # SYS-40: the digest's composition per topic, queryable from the row.
        composition = {
            sec["topic"]: {"articles": sec["article_count"], "clusters": sec["cluster_count"],
                           "shown": len(sec["clusters"])}
            for sec in sections
        }
        composition[SUMMARIES_KEY] = stats.as_dict()   # SYS-68: not a topic; readers skip "_" keys
        composition[EDITION_KEY] = edition_stats
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
                    f"{cluster_count} clusters in {len(sections)} sections, {len(articles)} articles. "
                    f"{stats.describe()} | edition {edition_stats}")
        return DigestPath(file_path, note, edition_file)

    def _write_edition(self, target_date: date, sections: list, articles: list, stats: "SummaryStats",
                       digest_path: str) -> Tuple[dict, Optional[str]]:
        """(the `_edition` stats, the edition's path or None). A failure here
        never costs the digest: it is logged and reported, and a stale edition
        file of the same date is removed so it cannot be sent as today's."""
        path = newsletter_edition.edition_path(digest_path)
        # once the calls stopped (quota, outage), the editor is not asked either
        editor = None if stats.stopped else self._summarizer
        try:
            edition = newsletter_edition.build(editor, sections, target_date, len(articles),
                                               len(self._unique_sources(articles)))
            if edition is None:
                result = {"built": False, "reason": "no summarized story"}
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(edition.markdown)
                logger.info(f"Edition written to {path} ({edition.words} words, {edition.utama} top stories, "
                            f"{edition.sekilas} Sekilas lines, editor fallback: {edition.editor_fallback})")
                return edition.stats(), path
        except Exception as e:  # noqa: BLE001 -- the archive digest is already written and must be saved
            logger.exception("5-minute edition failed")
            result = {"built": False, "reason": f"{type(e).__name__}: {e}"[:300]}
        if os.path.exists(path):
            os.remove(path)
        return result, None

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
        (the clusters past the cap plus the unclustered articles).

        Clustering is per topic, then clusters of different topics that are as
        close as one cluster may be are merged into the section of the larger
        one (SYS-65), so a story whose articles got different topics is shown
        once."""
        by_topic: dict = {}
        for i, a in enumerate(articles):
            by_topic.setdefault(self.topic_of(a), []).append(i)
        entries, unclustered = [], {}
        for topic in SECTION_ORDER:
            idx = by_topic.get(topic)
            if not idx:
                continue
            if len(idx) >= NEWSLETTER_MIN_CLUSTER_SIZE:
                labels = self._cluster([vectors[i] for i in idx])
            else:
                labels = [-1] * len(idx)
            groups = self._group_by_label(idx, labels)
            unclustered[topic] = groups.pop(-1, [])
            entries += [{"topic": topic, "idx": group} for group in groups.values()]
        entries = self._merge_across_sections(entries, vectors)
        sections = []
        for topic in SECTION_ORDER:
            clusters = [self._describe_cluster([articles[i] for i in e["idx"]])
                        for e in entries if e["topic"] == topic]
            loose = unclustered.get(topic, [])
            if not clusters and not loose:
                continue
            clusters.sort(key=lambda c: (len(c["articles"]) * len(c["sources"]), len(c["articles"])), reverse=True)
            shown = clusters[:NEWSLETTER_MAX_CLUSTERS_PER_TOPIC]
            sections.append({
                "topic": topic,
                "article_count": len(loose) + sum(len(c["articles"]) for c in clusters),
                "cluster_count": len(clusters),
                "clusters": shown,
                "ranked": clusters,                       # SYS-67: every cluster, best first
                "unclustered": len(loose),
                "more": len(clusters) - len(shown) + len(loose),
            })
        return sections

    @staticmethod
    def _merge_across_sections(entries: list, vectors) -> list:
        """SYS-65: merge clusters whose average member-to-member cosine distance
        is at most NEWSLETTER_CLUSTER_DISTANCE -- the same cut the per-topic
        clustering uses -- whatever their topics, closest pair first. The merged
        cluster keeps the topic of the larger one, or of the earlier
        SECTION_ORDER topic on a tie. For unit vectors the average pairwise
        cosine similarity of two groups is the dot product of their sums over
        the product of their sizes, so each pass is one matrix product."""
        if len(entries) < 2:
            return entries
        import numpy as np
        v = np.asarray(vectors, dtype=float)
        norms = np.linalg.norm(v, axis=1, keepdims=True)
        v = np.divide(v, norms, out=np.zeros_like(v), where=norms > 0)
        sums = np.array([v[e["idx"]].sum(axis=0) for e in entries])
        sizes = np.array([len(e["idx"]) for e in entries], dtype=float)
        live = list(range(len(entries)))
        while len(live) > 1:
            s, n = sums[live], sizes[live]
            dist = 1.0 - (s @ s.T) / np.outer(n, n)
            np.fill_diagonal(dist, np.inf)
            a, b = np.unravel_index(np.argmin(dist), dist.shape)
            if dist[a, b] > NEWSLETTER_CLUSTER_DISTANCE:
                break
            keep, drop = sorted((live[a], live[b]), key=lambda k: (
                -len(entries[k]["idx"]), SECTION_ORDER.index(entries[k]["topic"])))
            entries[keep]["idx"] = entries[keep]["idx"] + entries[drop]["idx"]
            sums[keep] += sums[drop]
            sizes[keep] += sizes[drop]
            live.remove(drop)
        return [entries[k] for k in live]

    def _describe_cluster(self, cluster_articles: list) -> dict:
        return {
            "headline": self._pick_cluster_headline(cluster_articles),
            "sources":  self._unique_sources(cluster_articles),
            "links":    self._top_links(cluster_articles),
            "articles": cluster_articles,
        }

    # ── Cluster summarization ────────────────────────────────────────────────

    @staticmethod
    def _top_articles(articles: list) -> list:
        return sorted(
            articles,
            key=lambda a: SOURCE_AUTHORITY.get(a["source"].upper(), 0.5),
            reverse=True,
        )[:3]

    def headline_summary(self, articles: list) -> str:
        """What a cluster shows when no real summary was produced."""
        return "\n".join(f"- {a['headline']}" for a in self._top_articles(articles))

    def summarize_cluster(self, cluster: dict, rejections: list) -> Optional[story_summary.StorySummary]:
        """SYS-82 (#239): the cluster's structured summary, or None when the
        model's answer was refused twice (each refusal's reason is appended to
        `rejections`). An accepted summary is applied to the cluster (SYS-80).
        Raises QuotaExhausted or SummarizerError; the caller decides what a
        failure costs."""
        shown = story_summary.pick_articles(cluster["articles"])
        cluster["source_text"] = story_summary.source_text(shown)   # the edition's number guard reads it
        story = story_summary.summarize_story(self._summarizer, shown, rejections)
        if story is not None:
            self._apply_story(cluster, shown, story)
        return story

    def _apply_story(self, cluster: dict, shown: list, story: story_summary.StorySummary) -> None:
        """SYS-80 (#236): the story is what the model summarized, so its headline
        and links come only from the articles it marked `terkait`, and an
        article it marked `tidak_terkait` no longer counts as a portal that
        carried the story. Articles it did not see stay as clustered."""
        unrelated = {id(shown[i]) for i in story.tidak_terkait}
        related = [shown[i] for i in story.terkait]
        cluster["story"] = story
        cluster["headline"] = self._pick_cluster_headline(related)
        cluster["sources"] = self._unique_sources([a for a in cluster["articles"] if id(a) not in unrelated])
        cluster["links"] = self._top_links(related)

    def _summarize_sections(self, sections: list) -> SummaryStats:
        """SYS-68 (#216): summarize every shown cluster, counting the real
        summaries. A quota error stops the calls at once (the provider refuses
        all of them today); NEWSLETTER_MAX_CONSECUTIVE_SUMMARY_ERRORS failures
        in a row stop them too (an outage). A refused answer (SYS-82) is not an
        outage: the provider answered. Every cluster without a summary shows
        its headlines, and the stats say how many."""
        stats = SummaryStats(provider=getattr(self._summarizer, "name", None))
        if self._summarizer is None:
            stats.stopped = "no_provider"
        else:
            self._diversify(sections, stats)
        clusters = [c for section in sections for c in section["clusters"]]
        stats.total = len(clusters)
        consecutive_errors = 0
        for cluster in clusters:
            story, rejections = None, []
            if not stats.stopped:
                try:
                    story = self.summarize_cluster(cluster, rejections)
                    consecutive_errors = 0
                except QuotaExhausted as e:
                    stats.stopped = "quota"
                    quota = f" ({e.quota})" if e.quota else ""
                    logger.warning(f"Summarizer quota exhausted{quota}; the remaining clusters list headlines.")
                except SummarizerError as e:
                    consecutive_errors += 1
                    logger.warning(f"Summarization failed ({consecutive_errors} in a row): {e}. Using headlines.")
                    if consecutive_errors >= NEWSLETTER_MAX_CONSECUTIVE_SUMMARY_ERRORS:
                        stats.stopped = "errors"
            for reason in rejections:
                stats.rejections[reason] += 1
            if story is not None:
                stats.summarized += 1
                stats.first_try += not rejections
                continue
            if len(rejections) == 2:
                logger.warning(f"Summary refused twice ({', '.join(rejections)}); showing the headlines of "
                               f"{cluster['headline']!r}.")
            cluster["story"] = None
            cluster["fallback"] = self.headline_summary(cluster["articles"])
        return stats

    def _diversify(self, sections: list, stats: SummaryStats) -> None:
        """SYS-67 (#215): replace each section's shown clusters by the best ones with at
        most NEWSLETTER_MAX_CLUSTERS_PER_STORY of any one story, as the summarizer
        groups them. A section whose grouping fails is shown as ranked and counted;
        a quota error stops the calls (the summaries stop with it)."""
        if not NEWSLETTER_MAX_CLUSTERS_PER_STORY:
            return
        pool_size = 2 * NEWSLETTER_MAX_CLUSTERS_PER_TOPIC
        consecutive_errors = 0
        for section in sections:
            ranked = section["ranked"]
            if len(ranked) <= NEWSLETTER_MAX_CLUSTERS_PER_STORY:
                continue                  # too few clusters for one story to crowd the section
            pool = ranked[:pool_size]
            try:
                groups = group_clusters(self._summarizer, pool)
            except QuotaExhausted as e:
                stats.stopped = "quota"
                logger.warning(f"Summarizer quota exhausted while grouping stories ({e.quota or 'unnamed quota'}).")
                return
            except SummarizerError as e:
                stats.groups_failed += 1
                consecutive_errors += 1
                logger.warning(f"Story grouping failed for {section['topic']}: {e}. Showing the ranked clusters.")
                if consecutive_errors >= NEWSLETTER_MAX_CONSECUTIVE_SUMMARY_ERRORS:
                    stats.stopped = "errors"
                    return
                continue
            consecutive_errors = 0
            stats.groups_ok += 1
            shown = pick_shown(pool, groups, NEWSLETTER_MAX_CLUSTERS_PER_STORY, NEWSLETTER_MAX_CLUSTERS_PER_TOPIC)
            section["clusters"] = shown
            section["more"] = section["cluster_count"] - len(shown) + section["unclustered"]

    @staticmethod
    def _summary_note(stats: SummaryStats) -> Optional[str]:
        """None when the summaries are good enough; otherwise the sentence the
        operator needs, also logged at ERROR (SYS-68)."""
        if stats.total == 0 or stats.share >= NEWSLETTER_MIN_SUMMARY_SHARE:
            return None
        note = f"digest degraded: {stats.describe()}"
        logger.error(note)
        return note

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
        """Cluster labels, -1 for an article in no cluster of at least
        NEWSLETTER_MIN_CLUSTER_SIZE. Average linkage on cosine distance, cut
        at NEWSLETTER_CLUSTER_DISTANCE: a cluster's members are close to the
        cluster as a whole, not merely chained to one neighbour (SYS-40)."""
        import collections
        from sklearn.cluster import AgglomerativeClustering
        labels = AgglomerativeClustering(
            n_clusters=None, metric="cosine", linkage="average",
            distance_threshold=NEWSLETTER_CLUSTER_DISTANCE,
        ).fit(vectors).labels_.tolist()
        sizes = collections.Counter(labels)
        return [label if sizes[label] >= NEWSLETTER_MIN_CLUSTER_SIZE else -1 for label in labels]

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
        """Up to three links, one per outlet, most authoritative outlets first
        (SYS-69). A story only two outlets carried fills its third slot with a
        second article of the best outlet rather than leaving it empty."""
        ranked = sorted(
            (a for a in articles if a.get("link")),
            key=lambda a: SOURCE_AUTHORITY.get(a["source"].upper(), 0.5),
            reverse=True,
        )
        picked, seen = [], set()
        for a in ranked:
            if a["source"].upper() not in seen:
                seen.add(a["source"].upper())
                picked.append(a)
        picked = picked[:_MAX_LINKS]
        picked += [a for a in ranked if a not in picked][:_MAX_LINKS - len(picked)]
        return [{"source": a["source"], "link": a["link"], "headline": a["headline"]} for a in picked]

    @staticmethod
    def _link_label(link: dict) -> str:
        """`Outlet: headline`, the headline cut at a word. Every article of a
        digest is from the digest's own day, so a date says nothing (SYS-69).
        The outlet is its brand name, not the source enum (SYS-84)."""
        headline = " ".join(link["headline"].replace("[", "(").replace("]", ")").split())
        if len(headline) > _LINK_LABEL_CHARS:
            headline = headline[:_LINK_LABEL_CHARS].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"
        outlet = copy.outlet(link["source"])
        return f"{outlet}: {headline}" if headline else outlet

    def _render_cluster(self, cluster: dict) -> List[str]:
        """SYS-82: `### judul`, the `inti` sentence, the `poin` bullets and
        'Mengapa penting' when the story has a summary; the portal headline and
        its headline list when it fell back. Then who reported it and the links."""
        story = cluster.get("story")
        if story is not None:
            lines = [f"### {story.judul}", "", story.inti, ""] + [f"- {p}" for p in story.poin]
            if story.poin:
                lines.append("")
            if story.mengapa_penting:
                lines.append(f"**{copy.WHY_IT_MATTERS}** {story.mengapa_penting}")
        else:
            lines = [f"### {cluster['headline']}", "",
                     cluster.get("fallback") or self.headline_summary(cluster["articles"]), ""]
        outlets = [copy.outlet(s) for s in cluster["sources"]]
        lines.append(f"**{copy.REPORTED_BY.format(n=len(outlets))}:** {' · '.join(outlets)}")
        link_parts = [f"[{self._link_label(l)}]({l['link']})" for l in cluster["links"]]
        if link_parts:
            lines.append(f"**{copy.RELATED}** {' · '.join(link_parts)}")
        return lines + [""]

    def _render_markdown(self, target_date: date, sections: list, all_articles: list,
                         stats: Optional[SummaryStats] = None) -> str:
        """The full digest (the archive). SYS-84: the reader's wording, a
        notice at the top when some stories have no summary, and a footer that
        says what the digest is made from and that AI wrote it -- the pipeline's
        telemetry is the operator's (stats.describe()), not the reader's."""
        lines = [f"# {copy.TITLE}", "", f"> {copy.DATELINE_FULL.format(tanggal=copy.tanggal(target_date))}", ""]
        if stats is not None and stats.fallback:
            lines += [f"> {copy.degraded(stats.fallback)}", ""]
        lines += ["---", ""]
        for section in sections:
            lines += [f"## {SECTION_TITLES[section['topic']]}", ""]
            for cluster in section["clusters"]:
                lines += self._render_cluster(cluster)
            if section["more"]:
                lines.append(f"*{copy.MORE_IN_SECTION.format(n=copy.angka(section['more']))}*")
            lines += ["", "---", ""]
        lines.append(f"*{copy.footer(len(all_articles), len(self._unique_sources(all_articles)))}*")
        return "\n".join(lines) + "\n"

    def _write_empty_digest(self, target_date: date, start_ms: int) -> "DigestPath":
        """SYS-84: an empty day says what it usually means (a collection
        problem), in the reader's words. No edition is built for it."""
        os.makedirs(DIGESTS_DIR, exist_ok=True)
        file_name = target_date.strftime("%Y-%m-%d.md")
        file_path = os.path.join(DIGESTS_DIR, file_name)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(f"# {copy.TITLE}\n\n"
                    f"> {copy.DATELINE_FULL.format(tanggal=copy.tanggal(target_date))}\n\n"
                    f"{copy.empty_day(target_date)}\n")
        stale_edition = newsletter_edition.edition_path(file_path)
        if os.path.exists(stale_edition):
            os.remove(stale_edition)
        generation_ms = _now_ms() - start_ms
        self.ds.save_digest(
            digest_date=target_date, file_path=file_path,
            cluster_count=0, article_count=0, categories={},
            source_ids=[], generation_ms=generation_ms,
        )
        return DigestPath(file_path)


def _now_ms() -> int:
    return int(datetime.utcnow().timestamp() * 1000)
