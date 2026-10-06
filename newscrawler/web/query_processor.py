"""Hybrid retrieval and the answer for the search page (ADR-005).

`retrieve` finds the articles: FAISS (L2 paragraphs) and Postgres full-text,
merged per article, given their headline / link / portal / date / topic from
the database (SYS-92: FAISS metadata is neither the topic nor always the right
date, SYS-91), filtered (SYS-100), re-ranked, cut at the relevance floor.

`answer` writes the answer through the shared Summarizer (SYS-98) and returns a
state, never an error as text (SYS-94): `ok`, `unavailable` (no provider, a
daily quota, or the page's own daily cap), `failed` (this call failed; retry),
`no_hits` (nothing relevant, so no call is made). Its usage is counted under
`web:<model>` with tokens and dollars, apart from the extraction's budget.
"""
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
    RAG_MIN_SEMANTIC_SCORE,
    RAG_RECENCY_WEIGHT,
    RAG_SEMANTIC_WEIGHT,
    RAG_TOP_K,
)
from newscrawler.core.newsletter_copy import outlet
from newscrawler.core.peak_hours import cost_usd, is_peak
from newscrawler.core.summarizer import QuotaExhausted, SummarizerError, build_summarizer
from newscrawler.web import answer as answer_text
from newscrawler.web.filters import Filters

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

SEARCH_K = 20               # paragraphs per retriever without a filter
SNIPPET_CHARS = 280
USAGE_PREFIX = "web:"       # api_usage_log key of the page's calls: never the extraction's own key

OK, UNAVAILABLE, FAILED, NO_HITS = "ok", "unavailable", "failed", "no_hits"
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


class QueryProcessor:
    def __init__(self, faiss_datasource, db_client, summarizer=_FROM_CONFIG, usage=_FROM_CONFIG):
        """summarizer: anything with `name`, `priced` and `complete(prompt)` (ADR-005); left out,
        it is built from RAG_LLM_PROVIDER. usage: anything with `increment_api_call_count` and
        `get_today_api_usage` (api_usage_log); left out, the knowledge datasource on this client."""
        self.faiss_ds = faiss_datasource
        self.client = db_client
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
        self.summarizer = summarizer
        self.usage = usage

    # ── Retrieval ────────────────────────────────────────────────────────────

    def retrieve(self, question: str, filters: Optional[Filters] = None, today: Optional[date] = None) -> List[dict]:
        """The relevant articles, best first, at most RAG_TOP_K, each with `n` (1-based)."""
        filters = filters or Filters()
        today = today or date.today()
        start = time.monotonic()
        k = RAG_FILTERED_K if filters.active else SEARCH_K
        semantic_hits = self.faiss_ds.search_l2(question, k=k)
        fts_hits = self._fts_search(question, SEARCH_K, filters, today)
        merged = self._attach_metadata(self._merge(semantic_hits, fts_hits))
        if filters.active:
            merged = self._apply_filters(merged, filters, today)
        ranked = self._re_rank(merged, today)
        # Drop weakly relevant hits, so an off-topic question returns nothing rather than the
        # nearest (but irrelevant) neighbours. Keyword (FTS) matches survive the semantic floor.
        relevant = [h for h in ranked
                    if h.get("semantic_score", 0.0) >= RAG_MIN_SEMANTIC_SCORE or h.get("bm25_score", 0.0) > 0
                    ][:RAG_TOP_K]
        for n, hit in enumerate(relevant, 1):
            hit["n"] = n
        logger.info(f"rag retrieve ms={int((time.monotonic() - start) * 1000)} semantic={len(semantic_hits)} "
                    f"fts={len(fts_hits)} kept={len(relevant)} filters={filters.describe()}")
        return relevant

    _FTS_FILTERS = (
        ("topic", "AND a.topic = :topic"),
        ("source", "AND s.sources = :source"),
        ("from_day", "AND s.posted_at >= :from_day"),
        ("to_day", "AND s.posted_at <= :to_day"),
    )

    def _fts_search(self, query: str, k: int, filters: Filters, today: date) -> List[dict]:
        start_day, end_day = filters.bounds(today)
        params = {"query": query, "k": k, "topic": filters.topic, "source": filters.source,
                  "from_day": int(start_day.strftime("%Y%m%d")) if start_day else None,
                  "to_day": int(end_day.strftime("%Y%m%d")) if end_day else None}
        # Fixed fragments, chosen by which filters are set; the values are bind parameters only.
        where = " ".join(sql for name, sql in self._FTS_FILTERS if params[name] is not None)
        join = "LEFT JOIN articles a ON a.sitemap_id = c.sitemap_id" if filters.topic else ""
        sql = text(f"""
            SELECT c.chunk_id, c.text_content, c.sitemap_id,
                   ts_rank(c.fts_vector, plainto_tsquery('simple', :query)) AS bm25_score
            FROM chunks c
            JOIN sitemaps s ON c.sitemap_id = s.sitemap_id
            {join}
            WHERE c.fts_vector @@ plainto_tsquery('simple', :query)
              AND c.chunk_level = 2
              {where}
            ORDER BY bm25_score DESC
            LIMIT :k
        """)
        try:
            with self.client.get_session() as session:
                rows = session.execute(sql, {key: v for key, v in params.items()
                                             if key in ("query", "k") or v is not None}).fetchall()
            return [{"chunk_id": row.chunk_id, "text_content": row.text_content, "sitemap_id": row.sitemap_id,
                     "bm25_score": float(row.bm25_score), "semantic_score": 0.0} for row in rows]
        except Exception as e:  # noqa: BLE001 -- keyword search is one of two retrievers
            logger.warning(f"FTS search failed: {type(e).__name__}: {e}")
            return []

    @staticmethod
    def _merge(semantic: List[dict], fts: List[dict]) -> List[dict]:
        """One hit per article: its best paragraph from either retriever, both scores."""
        combined: dict = {}
        for hit in semantic:
            sid = hit.get("sitemap_id")
            if sid not in combined:
                combined[sid] = dict(hit)
                combined[sid].setdefault("bm25_score", 0.0)
            else:
                combined[sid]["semantic_score"] = max(combined[sid].get("semantic_score", 0.0),
                                                      hit.get("semantic_score", 0.0))
        for hit in fts:
            sid = hit.get("sitemap_id")
            if sid not in combined:
                combined[sid] = dict(hit)
                combined[sid].setdefault("semantic_score", 0.0)
            else:
                combined[sid]["bm25_score"] = max(combined[sid].get("bm25_score", 0.0), hit.get("bm25_score", 0.0))
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
    def _re_rank(hits: List[dict], today: Optional[date] = None) -> List[dict]:
        today = today or date.today()
        for h in hits:
            d = h.get("posted_date") or posted_date(h.get("posted_at"))
            recency = max(0.0, 1.0 - max(0, (today - d).days) * 0.1 / 7) if d else 0.5
            # ts_rank is in [0, 1] but usually tiny; scale it up
            bm25_norm = min(1.0, h.get("bm25_score", 0.0) * 10)
            h["final_score"] = (h.get("semantic_score", 0.0) * RAG_SEMANTIC_WEIGHT
                                + bm25_norm * RAG_BM25_WEIGHT + recency * RAG_RECENCY_WEIGHT)
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

    def _over_daily_cap(self, key: str) -> bool:
        try:
            spent = self.usage.get_today_api_usage(key).cost_usd
        except Exception as e:  # noqa: BLE001 -- an unreadable ledger must not hide every answer
            logger.warning(f"Could not read today's {key} spend; answering anyway: {type(e).__name__}: {e}")
            return False
        if spent >= RAG_DAILY_COST_LIMIT_USD:
            logger.warning(f"rag answer unavailable: {key} spent ${spent:.4f} today, "
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
              today: Optional[date] = None) -> dict:
        hits = self.retrieve(question, filters, today)
        result = self.answer(question, hits, session_history, today)
        return {
            "question": question,
            "answer_status": result.status,
            "answer": result.text,
            "numbers_unverified": result.unverified is not None,
            "sources": [card(h["n"], h) for h in hits],
        }
