import logging
from datetime import date, datetime, timedelta
from typing import List, Optional

from sqlalchemy import text

from newscrawler.core.constants import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    RAG_BM25_WEIGHT,
    RAG_RECENCY_WEIGHT,
    RAG_SEMANTIC_WEIGHT,
    RAG_TOP_K,
    RAG_MIN_SEMANTIC_SCORE,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_ANSWER_PROMPT = (
    "Jawab pertanyaan berikut HANYA menggunakan konteks yang diberikan.\n"
    "Kutip sumber dalam format [Nama Sumber, Tanggal].\n"
    "Jika tidak yakin, katakan demikian.\n\n"
    "Konteks:\n{context}\n\n"
    "Riwayat percakapan:\n{history}\n\n"
    "Pertanyaan: {question}\n\n"
    "Jawaban:"
)


class QueryProcessor:
    def __init__(self, faiss_datasource, db_client):
        self.faiss_ds = faiss_datasource
        self.client   = db_client

        if GEMINI_API_KEY:
            from google import genai
            # Initialize the client instead of using a global configuration.
            # (If you set GEMINI_API_KEY as an environment var, you can just use genai.Client())
            self._gemini = genai.Client(api_key=GEMINI_API_KEY)
        else:
            logger.warning("GEMINI_API_KEY not set — RAG answers will be disabled.")
            self._gemini = None

    def query(
        self,
        question: str,
        session_history: List[dict],
        date_from: Optional[date] = None,
        date_to: Optional[date]   = None,
        category: Optional[str]   = None,
        source: Optional[str]     = None,
    ) -> dict:
        start = _now_ms()

        # 1 & 2 — Semantic + FTS retrieval
        semantic_hits = self.faiss_ds.search_l2(question, k=20)
        fts_hits      = self._fts_search(question, k=20)

        # 3 — Merge & deduplicate by sitemap_id
        merged = self._merge(semantic_hits, fts_hits)

        # 4 — Apply optional filters
        if date_from or date_to or category or source:
            merged = self._apply_filters(merged, date_from, date_to, category, source)

        # 5 — Re-rank, then drop weakly-relevant hits so off-topic queries return
        #     nothing rather than the nearest (but irrelevant) neighbours. Keyword (FTS)
        #     matches are kept even below the semantic floor.
        ranked = self._re_rank(merged)
        relevant = [
            h for h in ranked
            if h.get("semantic_score", 0.0) >= RAG_MIN_SEMANTIC_SCORE
            or h.get("bm25_score", 0.0) > 0
        ][:RAG_TOP_K]

        # 6 — Fetch parent L1 context for top chunks
        enriched = self._enrich_with_parent_context(relevant)

        # 7 — Generate answer
        answer = self._generate_answer(question, enriched, session_history)

        sources = [
            {
                "title":    h.get("title", ""),
                "source":   h.get("source", ""),
                "posted_at": h.get("posted_at", ""),
                "link":     h.get("link", ""),
                "snippet":  h.get("text_content", "")[:300],
            }
            for h in enriched
        ]

        return {
            "answer":      answer,
            "sources":     sources,
            "chunks_used": len(enriched),
            "query_ms":    _now_ms() - start,
        }

    # ── FTS search ───────────────────────────────────────────────────────────

    def _fts_search(self, query: str, k: int) -> List[dict]:
        sql = text("""
            SELECT c.chunk_id, c.text_content, c.sitemap_id, c.chunk_level,
                   ts_rank(c.fts_vector, plainto_tsquery('simple', :query)) AS bm25_score,
                   s.sources AS source, s.posted_at, s.headline AS title, s.category,
                   s.link
            FROM chunks c
            JOIN sitemaps s ON c.sitemap_id = s.sitemap_id
            WHERE c.fts_vector @@ plainto_tsquery('simple', :query)
              AND c.chunk_level = 2
            ORDER BY bm25_score DESC
            LIMIT :k
        """)
        try:
            with self.client.get_session() as session:
                rows = session.execute(sql, {"query": query, "k": k}).fetchall()
            return [
                {
                    "chunk_id":     row.chunk_id,
                    "text_content": row.text_content,
                    "sitemap_id":   row.sitemap_id,
                    "bm25_score":   float(row.bm25_score),
                    "source":       row.source or "",
                    "posted_at":    str(row.posted_at) if row.posted_at else "",
                    "title":        row.title or "",
                    "category":     row.category or "",
                    "link":         row.link or "",
                }
                for row in rows
            ]
        except Exception as e:
            logger.warning(f"FTS search failed: {e}")
            return []

    # ── Merge ────────────────────────────────────────────────────────────────

    @staticmethod
    def _merge(semantic: List[dict], fts: List[dict]) -> List[dict]:
        combined: dict = {}

        for hit in semantic:
            sid = hit.get("sitemap_id")
            if sid not in combined:
                combined[sid] = dict(hit)
                combined[sid].setdefault("bm25_score", 0.0)
            else:
                combined[sid]["semantic_score"] = hit.get("semantic_score", 0.0)

        for hit in fts:
            sid = hit.get("sitemap_id")
            if sid not in combined:
                combined[sid] = dict(hit)
                combined[sid].setdefault("semantic_score", 0.0)
            else:
                combined[sid]["bm25_score"] = hit.get("bm25_score", 0.0)
                if not combined[sid].get("link"):
                    combined[sid]["link"] = hit.get("link", "")

        return list(combined.values())

    # ── Filters ──────────────────────────────────────────────────────────────

    @staticmethod
    def _apply_filters(
        hits: List[dict],
        date_from: Optional[date],
        date_to: Optional[date],
        category: Optional[str],
        source: Optional[str],
    ) -> List[dict]:
        out = []
        for h in hits:
            posted = h.get("posted_at", "")
            if posted:
                try:
                    posted_date = datetime.strptime(str(posted)[:8], "%Y%m%d").date()
                    if date_from and posted_date < date_from:
                        continue
                    if date_to and posted_date > date_to:
                        continue
                except ValueError:
                    pass
            if category and category.lower() not in (h.get("category") or "").lower():
                continue
            if source and source.upper() not in (h.get("source") or "").upper():
                continue
            out.append(h)
        return out

    # ── Re-rank ──────────────────────────────────────────────────────────────

    @staticmethod
    def _re_rank(hits: List[dict]) -> List[dict]:
        today = date.today()
        for h in hits:
            posted = h.get("posted_at", "")
            try:
                posted_date = datetime.strptime(str(posted)[:8], "%Y%m%d").date()
                days_old = max(0, (today - posted_date).days)
                recency  = max(0.0, 1.0 - days_old * 0.1 / 7)
            except (ValueError, TypeError):
                recency = 0.5

            sem  = h.get("semantic_score", 0.0)
            bm25 = h.get("bm25_score", 0.0)

            # Normalize bm25 (ts_rank is [0,1] but often very small; scale up)
            bm25_norm = min(1.0, bm25 * 10)

            h["final_score"] = (
                sem  * RAG_SEMANTIC_WEIGHT +
                bm25_norm * RAG_BM25_WEIGHT +
                recency   * RAG_RECENCY_WEIGHT
            )

        return sorted(hits, key=lambda h: h["final_score"], reverse=True)

    # ── Context enrichment ───────────────────────────────────────────────────

    def _enrich_with_parent_context(self, hits: List[dict]) -> List[dict]:
        """Fetch the L1 (summary) chunk for each hit's article to give the LLM more context."""
        if not hits:
            return hits

        sitemap_ids = list({h["sitemap_id"] for h in hits if h.get("sitemap_id")})
        sql = text("""
            SELECT c.sitemap_id, c.text_content AS l1_text,
                   s.link, s.headline, s.sources AS source, s.posted_at
            FROM chunks c
            JOIN sitemaps s ON c.sitemap_id = s.sitemap_id
            WHERE c.sitemap_id = ANY(:ids) AND c.chunk_level = 1
        """)
        try:
            with self.client.get_session() as session:
                rows = session.execute(sql, {"ids": sitemap_ids}).fetchall()
            parent = {row.sitemap_id: row for row in rows}
        except Exception as e:
            logger.warning(f"Parent context fetch failed: {e}")
            parent = {}

        for h in hits:
            sid = h.get("sitemap_id")
            if sid and sid in parent:
                p = parent[sid]
                h.setdefault("link",    p.link or "")
                h.setdefault("title",   p.headline or h.get("title", ""))
                h.setdefault("source",  p.source or h.get("source", ""))
                h["l1_text"] = p.l1_text or ""

        return hits

    # ── Answer generation ────────────────────────────────────────────────────

    def _generate_answer(
        self, question: str, hits: List[dict], history: List[dict]
    ) -> str:
        if not self._gemini:
            return (
                "RAG answers require GEMINI_API_KEY. "
                "Retrieved chunks are shown in the sources section."
            )

        context_parts = []
        for i, h in enumerate(hits, 1):
            posted = h.get("posted_at", "")
            try:
                pd = datetime.strptime(str(posted)[:8], "%Y%m%d")
                date_str = pd.strftime("%d %b %Y")
            except Exception:
                date_str = str(posted)
            source  = h.get("source", "")
            title   = h.get("title", "")
            snippet = h.get("text_content", "")[:600]
            context_parts.append(
                f"[{i}] [{source}, {date_str}] {title}\n{snippet}"
            )

        history_str = "\n".join(
            f"Q: {turn['question']}\nA: {turn['answer']}"
            for turn in history[-3:]
        ) if history else "Tidak ada riwayat."

        prompt = _ANSWER_PROMPT.format(
            context="\n\n".join(context_parts),
            history=history_str,
            question=question,
        )

        try:
            resp = self._gemini.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt
            )
            return resp.text.strip()
        except Exception as e:
            logger.error(f"Gemini answer generation failed: {e}")
            return f"Maaf, terjadi kesalahan saat menghasilkan jawaban: {e}"


def _now_ms() -> int:
    return int(datetime.utcnow().timestamp() * 1000)
