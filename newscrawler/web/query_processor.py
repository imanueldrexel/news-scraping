"""Hybrid retrieval and the answer for the search page (ADR-005, ADR-007).

`retrieve` finds the articles: FAISS (L2 paragraphs) and Postgres full-text,
merged per article, given their headline / link / portal / date / topic from
the database (SYS-92: FAISS metadata is neither the topic nor always the right
date, SYS-91), filtered (SYS-100), scored on both signals (SYS-106), re-ranked,
cut at the relevance floor. A "this week" question prefers the last 7 days (a soft window,
ADR-012). A follow-up is first rewritten into a standalone question by one
model call, with a deterministic fallback (`followup`, ADR-010).

`answer` writes the answer through the shared Summarizer (SYS-98) and returns a
state, never an error as text (SYS-94): `ok`, `unavailable` (no provider, a
daily quota, or the page's own daily cap), `failed` (this call failed; retry),
`no_hits` (nothing relevant, so no call is made). Its usage is counted under
`web:<model>` with tokens and dollars, apart from the extraction's budget.
"""
import dataclasses
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional, Sequence

from sqlalchemy import text

from newscrawler.core import web_copy as copy
from newscrawler.core.constants import (
    RAG_ANSWER_MAX_TOKENS,
    RAG_ANSWER_TIMEOUT_S,
    RAG_BM25_WEIGHT,
    RAG_DAILY_COST_LIMIT_USD,
    RAG_FILTERED_K,
    RAG_LLM_PROVIDER,
    RAG_MIN_KEYWORD_COVERAGE,
    RAG_MIN_SEMANTIC_SCORE,
    RAG_RECENCY_WEIGHT,
    RAG_REWRITE_MAX_TOKENS,
    RAG_REWRITE_TIMEOUT_S,
    RAG_SEMANTIC_WEIGHT,
    RAG_TOP_K,
)
from newscrawler.core.newsletter_copy import outlet
from newscrawler.core.peak_hours import cost_usd, is_peak
from newscrawler.core.summarizer import QuotaExhausted, SummarizerError, build_summarizer
from newscrawler.web import answer as answer_text
from newscrawler.web import followup, keywords
from newscrawler.web.filters import Filters

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

SEARCH_K = 20               # paragraphs of the keyword half
# SYS-107 (#277): FAISS paragraphs without a filter. A daily story (gold, rupiah) has hundreds of
# near-identical paragraphs, and the 20 most similar were an arbitrary, often week-old, slice.
SEMANTIC_K = 100
# SYS-105 (#275): a matched paragraph shorter than this is a sign-off, a caption or a credit line,
# never an answer; and a vector of a few words lies near every question (a "hub").
MIN_PARAGRAPH_WORDS = 15
SNIPPET_CHARS = 280
USAGE_PREFIX = "web:"       # api_usage_log key of the page's calls: never the extraction's own key

OK, UNAVAILABLE, FAILED, NO_HITS = "ok", "unavailable", "failed", "no_hits"
SEMANTIC, KEYWORD, BOTH = "semantic", "keyword", "both"     # which retriever found an article
_FROM_CONFIG = object()


@dataclass
class AnswerResult:
    status: str
    text: str = ""                          # the cleaned answer, citations as [n]
    blocks: list = field(default_factory=list)
    unverified: Optional[str] = None        # the first number the cited articles lack
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


def posted_date(value) -> Optional[date]:
    """An int / str yyyymmdd (sitemaps.posted_at) as a date; None when it is not one."""
    try:
        return datetime.strptime(str(value)[:8], "%Y%m%d").date()
    except (TypeError, ValueError):
        return None


def substantial(hits: List[dict]) -> List[dict]:
    """SYS-105: the hits whose matched paragraph is long enough to answer anything."""
    return [h for h in hits if len((h.get("text_content") or "").split()) >= MIN_PARAGRAPH_WORDS]


def recency(d: Optional[date], today: date, horizon: Optional[int] = None) -> float:
    """In [0, 1]. By default a slow fade, 0.1 a week. For a question that asks for recent news
    (SYS-107) it halves at the cue's horizon (keywords.recency_cue: 1 day for "hari ini"), so
    today's report beats last week's near-copy. An undated article sits in the middle."""
    if d is None:
        return 0.5
    days = max(0, (today - d).days)
    return 1.0 / (1 + days / horizon) if horizon else max(0.0, 1.0 - days * 0.1 / 7)


def passes_floor(hit: dict) -> bool:
    """Relevant enough to show: similar enough, or covering most of the question's weighted words
    (ADR-006). Below both, an off-topic question gets nothing rather than its nearest neighbours."""
    return (hit.get("semantic_score", 0.0) >= RAG_MIN_SEMANTIC_SCORE
            or hit.get("keyword_score", 0.0) >= RAG_MIN_KEYWORD_COVERAGE)


def safe_link(link: Optional[str]) -> str:
    """The article URL when it is http(s); '' otherwise (a scraped `javascript:` must not become an href)."""
    link = (link or "").strip()
    return link if link.lower().startswith(("http://", "https://")) else ""


def snippet(hit: dict) -> str:
    body = " ".join((hit.get("text_content") or "").split())
    if len(body) <= SNIPPET_CHARS:
        return body
    cut = body[:SNIPPET_CHARS].rsplit(" ", 1)[0]
    return f"{cut}…"


def card(n: int, hit: dict) -> dict:
    """What the page and the JSON API show for source n. The internal source name is kept only
    as `source` (a filter value), never as display text."""
    d = hit.get("posted_date")
    return {
        "n": n,
        "outlet": outlet(hit.get("source", "")),
        "source": hit.get("source", ""),
        "date": copy.tanggal_kartu(d),
        "posted_date": d.isoformat() if d else None,
        "title": hit.get("title", ""),
        "link": safe_link(hit.get("link")),
        "topic": hit.get("topic"),
        "topic_name": copy.topic_name(hit.get("topic")),
        "snippet": snippet(hit),
    }


def _no_wait(seconds: float) -> None:
    """The rewrite's summarizer never sleeps on a rate limit: the cards are waiting (ADR-010)."""
    raise SummarizerError(f"rate limited (retry in {seconds:.0f}s); not waiting")


class QueryProcessor:
    rewriter = None     # no rewrite call: every follow-up takes the fallback (ADR-010)

    def __init__(self, faiss_datasource, db_client, summarizer=_FROM_CONFIG, usage=_FROM_CONFIG,
                 rewriter=_FROM_CONFIG):
        """summarizer: anything with `name`, `priced` and `complete(prompt)` (ADR-005); left out,
        it is built from RAG_LLM_PROVIDER. usage: anything with `increment_api_call_count` and
        `get_today_api_usage` (api_usage_log); left out, the knowledge datasource on this client.
        rewriter: the same kind of object, for a follow-up's one-line rewrite (ADR-010); left out,
        RAG_LLM_PROVIDER's with the rewrite's short timeout, no retry and no wait."""
        self.faiss_ds = faiss_datasource
        self.client = db_client
        self.keyword_df = keywords.DocFrequency(db_client)
        if summarizer is _FROM_CONFIG:
            summarizer = build_summarizer(provider=RAG_LLM_PROVIDER, setting="RAG_LLM_PROVIDER",
                                          timeout_s=RAG_ANSWER_TIMEOUT_S, max_tokens=RAG_ANSWER_MAX_TOKENS)
            if summarizer is None:
                logger.warning(f"RAG_LLM_PROVIDER={RAG_LLM_PROVIDER!r} has no API key: the search page "
                               "shows articles without an AI answer.")
        if usage is _FROM_CONFIG:
            from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_knowledge_data_source import (  # noqa: E501
                SQLAlchemyKnowledgeDataSource,
            )
            usage = SQLAlchemyKnowledgeDataSource(db_client)
        if rewriter is _FROM_CONFIG:
            rewriter = build_summarizer(provider=RAG_LLM_PROVIDER, setting="RAG_LLM_PROVIDER",
                                        timeout_s=RAG_REWRITE_TIMEOUT_S, max_tokens=RAG_REWRITE_MAX_TOKENS,
                                        sleep=_no_wait, max_retries=0)
        self.summarizer = summarizer
        self.usage = usage
        self.rewriter = rewriter

    # ── Retrieval ────────────────────────────────────────────────────────────

    def retrieve(self, question: str, filters: Optional[Filters] = None, today: Optional[date] = None,
                 history: Sequence[dict] = ()) -> List[dict]:
        """The relevant articles, best first, at most RAG_TOP_K, each with `n` (1-based). `history` is
        the conversation so far: a follow-up is resolved against its previous questions (ADR-010)."""
        filters = filters or Filters()
        today = today or date.today()
        start = time.monotonic()
        ranked, counts = self.candidates(question, filters, today, history)
        relevant = [h for h in ranked if passes_floor(h)][:RAG_TOP_K]
        for n, hit in enumerate(relevant, 1):
            hit["n"] = n
        logger.info(f"rag retrieve ms={int((time.monotonic() - start) * 1000)} semantic={counts['semantic']} "
                    f"fts={counts['fts']} articles={len(ranked)} kept={len(relevant)} "
                    f"keyword_only={sum(1 for h in relevant if h.get('origin') == KEYWORD)} "
                    f"recent={counts['recent']} window={counts['window']} followup={bool(history)} "
                    f"rewrite={counts['rewrite']} "
                    f"filters={filters.describe()}")
        return relevant

    def candidates(self, question: str, filters: Filters, today: date, history: Sequence[dict] = ()):
        """Every candidate article, scored on both signals and ranked, before the floor and the cut
        (ADR-007). Returns (ranked hits, {"semantic", "fts", "recent", "window", "rewrite"} for the log).

        SYS-138 (ADR-012): a cue with a window ("pekan ini": 7 days) and no date filter of the
        reader's is retrieved within the window first. When fewer than RAG_TOP_K of its articles
        pass the floor, they come first and the unwindowed ranking fills the rest."""
        query = self.resolve(question, history)
        cue = keywords.recency_cue(query.cue_text)
        kq = self._keyword_query(*query.questions)
        window = self._soft_window(cue, filters)
        if window is None:
            ranked, counts = self._ranked(query.text, kq, filters, today, cue)
            counts["window"] = None
        else:
            ranked, counts = self._ranked(query.text, kq, window, today, cue)
            inside = [h for h in ranked if passes_floor(h)]
            counts["window"] = f"{window.days}d"
            if len(inside) < RAG_TOP_K:
                seen = {h.get("sitemap_id") for h in inside}
                everything, counts_all = self._ranked(query.text, kq, filters, today, cue)
                ranked = inside + [h for h in everything if h.get("sitemap_id") not in seen]
                counts = dict(counts_all, window=f"{window.days}d+{len(inside)}")
        counts.update(recent=f"{cue.days}d" if cue else None, rewrite=query.how)
        return ranked, counts

    def _ranked(self, text_: str, kq: Optional["keywords.KeywordQuery"], filters: Filters, today: date,
                cue: Optional["keywords.RecencyCue"]):
        """Both retrievers under `filters`, merged per article, filtered, scored on both signals and
        ranked. Returns (ranked hits, {"semantic", "fts"})."""
        semantic_hits = substantial(self.faiss_ds.search_l2(text_, k=RAG_FILTERED_K if filters.active else SEMANTIC_K))
        fts_hits = (substantial(self._fts_search(kq, SEARCH_K, filters, today, cue is not None))
                    if kq is not None else [])
        merged = self._attach_metadata(self._merge(semantic_hits, fts_hits))
        if filters.active:
            merged = self._apply_filters(merged, filters, today)
        self._complete_scores(text_, kq, merged)
        return self._re_rank(merged, today, cue), {"semantic": len(semantic_hits), "fts": len(fts_hits)}

    @staticmethod
    def _soft_window(cue: Optional["keywords.RecencyCue"], filters: Filters) -> Optional[Filters]:
        """SYS-138 (ADR-012): the filters of the cue's window, or None. A reader's own date filter
        (a range chip, a date) always wins over the cue."""
        if cue is None or not cue.window or filters.days or filters.date_from or filters.date_to:
            return None
        return dataclasses.replace(filters, days=cue.window)

    def resolve(self, question: str, history: Sequence[dict] = ()) -> "followup.Retrieval":
        """What this turn is retrieved on (ADR-010): a question without a thread as it is; a follow-up
        rewritten into a standalone question by one call, or by the deterministic fallback. The call
        is counted under `web:<model>` and capped by the page's daily spend, like the answer."""
        previous = followup.previous_questions(history)
        if not previous:
            return followup.alone(question)
        complete = None
        if self.rewriter is not None and not self._over_daily_cap(USAGE_PREFIX + self.rewriter.name, "rewrite"):
            complete = self.rewriter.complete
        rewritten, reply, ms, why = followup.rewrite(complete, question, previous)
        if reply is not None:
            dollars = (cost_usd(reply.input_tokens, reply.output_tokens, is_peak())
                       if self.rewriter.priced else 0.0)
            self._record(USAGE_PREFIX + self.rewriter.name, reply.input_tokens, reply.output_tokens, dollars)
        query = followup.resolve(question, previous, rewritten)
        logger.info(f"rag follow-up rewrite={query.how} ms={ms}"
                    + (f" fallback_because={why!r}" if why else "") + f" query={query.text[:200]!r}")
        return query

    def _keyword_query(self, question: str, *more: str) -> Optional["keywords.KeywordQuery"]:
        """The questions' weighted words (ADR-006), or None: no content word, every word a typo, or
        the df lookup failed (the semantic half still answers). Names are judged per question (SYS-140)."""
        try:
            question_terms = keywords.terms(question, *more)
            if not question_terms:
                return None
            return keywords.KeywordQuery.build(question_terms, self.keyword_df.get([t.word for t in question_terms]))
        except Exception as e:  # noqa: BLE001 -- keyword search is one of two retrievers
            logger.warning(f"Keyword query failed: {type(e).__name__}: {e}")
            return None

    _FTS_FILTERS = (
        ("topic", "AND a.topic = :topic"),
        ("source", "AND s.sources = :source"),
        ("from_day", "AND s.posted_at >= :from_day"),
        ("to_day", "AND s.posted_at <= :to_day"),
    )

    def _fts_search(self, kq: "keywords.KeywordQuery", k: int, filters: Filters, today: date,
                    recent: bool = False) -> List[dict]:
        """The paragraphs holding the question's rare words, by IDF-weighted coverage (ADR-006).
        `keyword_score` is that coverage, in [0, 1]."""
        try:
            sql, params = self._fts_sql(kq, k, filters, today, recent)
            with self.client.get_session() as session:
                rows = session.execute(sql, params).fetchall()
            return [{"chunk_id": row.chunk_id, "text_content": row.text_content, "sitemap_id": row.sitemap_id,
                     "embedding_id": row.embedding_id, "keyword_score": float(row.keyword_score),
                     "semantic_score": 0.0} for row in rows]
        except Exception as e:  # noqa: BLE001 -- keyword search is one of two retrievers
            logger.warning(f"FTS search failed: {type(e).__name__}: {e}")
            return []

    @staticmethod
    def _word_tests(kq: "keywords.KeywordQuery", vector: str):
        """(coverage SQL, {word: SQL that is 1 when `vector` holds it}, bind parameters). `vector` is a
        fixed SQL expression; every word and weight is a bind parameter."""
        params, has = {}, {}
        for i, w in enumerate(kq.words):
            params[f"t{i}"], params[f"w{i}"] = keywords.lexeme(w), kq.weights[w]
            has[w] = f"({vector} @@ to_tsquery('simple', :t{i}))::int"
        score = " + ".join(f"CAST(:w{i} AS float8) * {has[w]}" for i, w in enumerate(kq.words))
        return score, has, params

    @classmethod
    def _fts_sql(cls, kq: "keywords.KeywordQuery", k: int, filters: Filters, today: date, recent: bool = False):
        """The keyword query as fixed SQL fragments; every word and weight is a bind parameter.

        Equal coverage is broken by `ts_rank_cd` (ADR-006 measured newest-first there: it let
        off-topic recent paragraphs in). For a question that asks for the latest news (SYS-107)
        the newest of the paragraphs that hold every word come first: a daily story has hundreds
        of them and the rank among them is arbitrary."""
        start_day, end_day = filters.bounds(today)
        score, has, params = cls._word_tests(kq, "c.fts_vector")
        params.update({"k": k, "anchors": " | ".join(keywords.lexeme(w) for w in kq.anchors), "need": kq.need})
        rule = f"AND ({' + '.join(has[w] for w in kq.anchors)}) >= :need"
        if kq.names:
            rule += f" AND ({' + '.join(has[w] for w in kq.names)}) >= 1"
        filter_values = {"topic": filters.topic, "source": filters.source,
                         "from_day": int(start_day.strftime("%Y%m%d")) if start_day else None,
                         "to_day": int(end_day.strftime("%Y%m%d")) if end_day else None}
        # Fixed fragments, chosen by which filters are set; the values are bind parameters only.
        where = " ".join(sql for name, sql in cls._FTS_FILTERS if filter_values[name] is not None)
        params.update({name: v for name, v in filter_values.items() if v is not None})
        join = "LEFT JOIN articles a ON a.sitemap_id = c.sitemap_id" if filters.topic else ""
        newest = f"CASE WHEN ({score}) > 0.9999 THEN s.posted_at END DESC NULLS LAST, " if recent else ""
        sql = text(f"""
            SELECT c.chunk_id, c.text_content, c.sitemap_id, c.embedding_id, ({score}) AS keyword_score
            FROM chunks c
            JOIN sitemaps s ON c.sitemap_id = s.sitemap_id
            {join}
            WHERE c.fts_vector @@ to_tsquery('simple', :anchors)
              AND c.chunk_level = 2
              {rule}
              {where}
            ORDER BY keyword_score DESC, {newest}ts_rank_cd(c.fts_vector, to_tsquery('simple', :anchors)) DESC
            LIMIT :k
        """)
        return sql, params

    def _coverage(self, kq: "keywords.KeywordQuery", texts: List[str]) -> List[float]:
        """Each text's IDF-weighted coverage of the question (ADR-006's `keyword_score`), computed by
        the same `to_tsvector('simple', ...)` that `chunks.fts_vector` stores. One round trip."""
        score, _, params = self._word_tests(kq, "x.v")
        params["texts"] = list(texts)
        sql = text(f"""
            SELECT x.i, ({score}) AS coverage
            FROM (SELECT u.i, to_tsvector('simple', u.body) AS v
                  FROM unnest(CAST(:texts AS text[])) WITH ORDINALITY AS u(body, i)) AS x
            ORDER BY x.i
        """)
        with self.client.get_session() as session:
            return [float(row.coverage) for row in session.execute(sql, params).fetchall()]

    def _complete_scores(self, text_: str, kq: Optional["keywords.KeywordQuery"], hits: List[dict]) -> None:
        """SYS-106 (#276): an article only one retriever found gets the other signal's score for its
        own paragraph, so the re-rank compares like with like. A missing score used to count as 0:
        a keyword-only hit scored at most 0.40 and never reached the five sources (0 of 95), and a
        FAISS hit the keyword half had not returned lost its words' share. On a failure the
        missing score stays 0, as before."""
        keyword_only = [h for h in hits if h.get("origin") == KEYWORD]
        if keyword_only:
            try:
                scores = self.faiss_ds.similarity(text_, [h.get("text_content") or "" for h in keyword_only],
                                                  [h.get("embedding_id") for h in keyword_only])
                for h, s in zip(keyword_only, scores):
                    h["semantic_score"] = s
            except Exception as e:  # noqa: BLE001 -- the hits keep their keyword score
                logger.warning(f"Semantic score of keyword-only hits failed: {type(e).__name__}: {e}")
        semantic_only = [h for h in hits if h.get("origin") == SEMANTIC]
        if kq is not None and semantic_only:
            try:
                for h, c in zip(semantic_only, self._coverage(kq, [h.get("text_content") or "" for h in semantic_only])):
                    h["keyword_score"] = c
            except Exception as e:  # noqa: BLE001 -- the hits keep their semantic score
                logger.warning(f"Keyword coverage of semantic-only hits failed: {type(e).__name__}: {e}")

    @staticmethod
    def _merge(semantic: List[dict], fts: List[dict]) -> List[dict]:
        """One hit per article: its best paragraph from either retriever, both scores, and which
        retriever found it (`origin`: semantic / keyword / both)."""
        combined: dict = {}
        for hit in semantic:
            sid = hit.get("sitemap_id")
            if sid not in combined:
                combined[sid] = dict(hit, origin=SEMANTIC)
                combined[sid].setdefault("keyword_score", 0.0)
            else:
                combined[sid]["semantic_score"] = max(combined[sid].get("semantic_score", 0.0),
                                                      hit.get("semantic_score", 0.0))
        for hit in fts:
            sid = hit.get("sitemap_id")
            if sid not in combined:
                combined[sid] = dict(hit, origin=KEYWORD)
                combined[sid].setdefault("semantic_score", 0.0)
            else:
                combined[sid]["keyword_score"] = max(combined[sid].get("keyword_score", 0.0),
                                                      hit.get("keyword_score", 0.0))
                if combined[sid]["origin"] == SEMANTIC:
                    combined[sid]["origin"] = BOTH
        return list(combined.values())

    def _attach_metadata(self, hits: List[dict]) -> List[dict]:
        """Headline, link, portal, date and topic from the database, and the article's lead (L1).
        A hit whose sitemap has no article is dropped: the article row is what is searchable
        (a leftover vector of a rejected sitemap must not become a source). If the query
        fails, the hits keep the FAISS metadata and have no topic."""
        ids = [h["sitemap_id"] for h in hits if h.get("sitemap_id") is not None]
        if not ids:
            return hits
        sql = text("""
            SELECT s.sitemap_id, s.headline, s.link, s.sources, s.posted_at, a.topic,
                   l1.text_content AS l1_text
            FROM sitemaps s
            JOIN articles a ON a.sitemap_id = s.sitemap_id
            LEFT JOIN chunks l1 ON l1.sitemap_id = s.sitemap_id AND l1.chunk_level = 1
            WHERE s.sitemap_id = ANY(:ids)
        """)
        try:
            with self.client.get_session() as session:
                rows = {row.sitemap_id: row for row in session.execute(sql, {"ids": ids}).fetchall()}
        except Exception as e:  # noqa: BLE001 -- show the hits with what FAISS knows
            logger.warning(f"Article metadata fetch failed; using the index's metadata: {type(e).__name__}: {e}")
            for h in hits:
                h["posted_date"] = posted_date(h.get("posted_at"))
                h.setdefault("topic", None)
            return hits
        out = []
        for h in hits:
            row = rows.get(h.get("sitemap_id"))
            if row is None:
                continue
            h.update(title=row.headline or "", link=row.link or "", source=row.sources or "",
                     posted_at=row.posted_at, posted_date=posted_date(row.posted_at), topic=row.topic,
                     l1_text=row.l1_text or "")
            out.append(h)
        return out

    @staticmethod
    def _apply_filters(hits: List[dict], filters: Filters, today: date) -> List[dict]:
        start, end = filters.bounds(today)
        out = []
        for h in hits:
            d = h.get("posted_date")
            if (start or end) and d is None:
                continue
            if start and d < start or end and d > end:
                continue
            if filters.topic and h.get("topic") != filters.topic:
                continue
            if filters.source and (h.get("source") or "").upper() != filters.source:
                continue
            out.append(h)
        return out

    @staticmethod
    def _re_rank(hits: List[dict], today: Optional[date] = None,
                 cue: Optional["keywords.RecencyCue"] = None) -> List[dict]:
        """`cue`: the question asks for recent news (SYS-107, ADR-007). Recency then weighs the
        cue's weight and halves at its horizon, but only for an article that is relevant by meaning
        (semantic >= RAG_MIN_SEMANTIC_SCORE). A keyword match alone does not make today's article
        the answer: 'Siapa Menteri Keuangan sekarang?' ranked a rice-aid story first."""
        today = today or date.today()
        for h in hits:
            d = h.get("posted_date") or posted_date(h.get("posted_at"))
            semantic = h.get("semantic_score", 0.0)
            if cue is None:
                fresh = recency(d, today) * RAG_RECENCY_WEIGHT
            else:
                fresh = recency(d, today, cue.days) * cue.weight if semantic >= RAG_MIN_SEMANTIC_SCORE else 0.0
            # keyword_score is the IDF-weighted coverage, already in [0, 1] (ADR-006)
            h["final_score"] = semantic * RAG_SEMANTIC_WEIGHT + h.get("keyword_score", 0.0) * RAG_BM25_WEIGHT + fresh
        return sorted(hits, key=lambda h: h["final_score"], reverse=True)

    # ── Answer ───────────────────────────────────────────────────────────────

    def answer(self, question: str, hits: Sequence[dict], history: Sequence[dict],
               today: Optional[date] = None) -> AnswerResult:
        today = today or date.today()
        if not hits:
            return AnswerResult(NO_HITS)
        if self.summarizer is None:
            return AnswerResult(UNAVAILABLE)
        key = USAGE_PREFIX + self.summarizer.name
        if self._over_daily_cap(key):
            return AnswerResult(UNAVAILABLE)

        start = time.monotonic()
        try:
            reply = self.summarizer.complete(answer_text.build_prompt(question, hits, history, today))
        except QuotaExhausted as e:
            logger.warning(f"rag answer unavailable: {self.summarizer.name} daily quota ({e.quota or e})")
            return AnswerResult(UNAVAILABLE)
        except SummarizerError as e:
            logger.warning(f"rag answer failed: {e}")
            return AnswerResult(FAILED)
        except Exception as e:  # noqa: BLE001 -- the reader gets the articles and a retry, never a traceback
            logger.exception(f"rag answer failed unexpectedly: {type(e).__name__}: {e}")
            return AnswerResult(FAILED)

        dollars = cost_usd(reply.input_tokens, reply.output_tokens, is_peak()) if self.summarizer.priced else 0.0
        self._record(key, reply.input_tokens, reply.output_tokens, dollars)
        cleaned = answer_text.clean(reply.text)
        if not cleaned:
            logger.warning(f"rag answer failed: {self.summarizer.name} returned an empty answer")
            return AnswerResult(FAILED, input_tokens=reply.input_tokens, output_tokens=reply.output_tokens,
                                cost_usd=dollars)
        blocks = answer_text.parse(cleaned, len(hits))
        unverified = answer_text.unverified_number(cleaned, hits, answer_text.cited(blocks), today)
        logger.info(f"rag answer status=ok ms={int((time.monotonic() - start) * 1000)} model={self.summarizer.name} "
                    f"tokens={reply.input_tokens}/{reply.output_tokens} cost=${dollars:.5f} "
                    f"words={len(cleaned.split())} unverified={unverified!r}")
        return AnswerResult(OK, cleaned, blocks, unverified, reply.input_tokens, reply.output_tokens, dollars)

    def _over_daily_cap(self, key: str, what: str = "answer") -> bool:
        try:
            spent = self.usage.get_today_api_usage(key).cost_usd
        except Exception as e:  # noqa: BLE001 -- an unreadable ledger must not hide every answer
            logger.warning(f"Could not read today's {key} spend; answering anyway: {type(e).__name__}: {e}")
            return False
        if spent >= RAG_DAILY_COST_LIMIT_USD:
            logger.warning(f"rag {what} unavailable: {key} spent ${spent:.4f} today, "
                           f"RAG_DAILY_COST_LIMIT_USD={RAG_DAILY_COST_LIMIT_USD}")
            return True
        return False

    def _record(self, key: str, input_tokens: int, output_tokens: int, dollars: float) -> None:
        try:
            self.usage.increment_api_call_count(key, input_tokens=input_tokens, output_tokens=output_tokens,
                                                cost_usd=dollars)
        except Exception as e:  # noqa: BLE001 -- accounting must never cost the answer
            logger.warning(f"Could not count the {key} call in api_usage_log: {type(e).__name__}: {e}")

    # ── Both, for the JSON API ───────────────────────────────────────────────

    def query(self, question: str, session_history: Sequence[dict], filters: Optional[Filters] = None,
              today: Optional[date] = None, thread: Optional[Sequence[dict]] = None) -> dict:
        """`session_history`: the answered turns (the prompt). `thread`: every question asked in the
        session (retrieval, SYS-104); without it, the answered turns' questions."""
        hits = self.retrieve(question, filters, today, history=session_history if thread is None else thread)
        result = self.answer(question, hits, session_history, today)
        return {
            "question": question,
            "answer_status": result.status,
            "answer": result.text,
            "numbers_unverified": result.unverified is not None,
            "sources": [card(h["n"], h) for h in hits],
        }
