#!/usr/bin/env python3
"""
Backfill script: chunk and embed all articles not yet represented in the chunks table.

Idempotent — safe to run multiple times; only processes articles with no existing chunk rows.

Usage:
    python scripts/backfill_chunks.py [--batch-size N] [--dry-run]

Environment variables (loaded from .env if present):
    POSTGRES_DB_HOST   localhost
    POSTGRES_DB_PORT   5432
    POSTGRES_DB_USER   postgres
    POSTGRES_DB_PASS   password
    POSTGRES_DB_NAME   newsaggregator
    VECTOR_DB_DIR      ./vector_db
    EMBEDDING_MODEL_HF sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 (see core/constants.py)

SYS-10 (#28): this script used to default to EMBEDDING_MODEL=nomic-embed-text -- the
old Ollama model name (PRD Sec6.5) -- which 401s loading from HuggingFace via
SentenceTransformer, and would have written 768-d vectors into these indexes even if
it existed. It now always embeds with EMBEDDING_MODEL_HF, the same constant
ChunkFAISSDatasource (the real pipeline's embedder) reads, so a backfilled chunk's
vector is comparable to a live-crawled one. EMBEDDING_DIM is read off the loaded
model rather than hardcoded, so a future EMBEDDING_MODEL_HF change can't silently
create a dimension-mismatched index here again.

Note this script's FAISS layout (VECTOR_DB_DIR/faiss_l1.index + faiss_l2.index, a raw
IndexFlatIP with sequential-int "l1:N"/"l2:N" embedding_ids) is its own, separate from
the live pipeline's NEWS_L1/NEWS_L2 (LangChain FAISS, UUID docstore keys) -- fixing
the model/dimension here does not merge the two indexes. Chunks this script writes to
Postgres are real; the vectors it writes go to VECTOR_DB_DIR, not NEWS_L1/NEWS_L2, so
they won't be found by search_l2() until that separate gap is addressed (flagged, not
scoped to SYS-10 -- see DBT-10's note that this script "targets a different index
layout").

Requirements (not in requirements.txt yet):
    pip install sentence-transformers faiss-cpu numpy
"""

import argparse
import ast
import json
import logging
import os
import sys

import numpy as np
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from sqlalchemy import text

from newscrawler.core.chunker import HierarchicalChunker
from newscrawler.core.constants import EMBEDDING_MODEL_HF
from newscrawler.domain.dtos.dataflow.details.news_details_dto import NewsDetailsDTO
from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

VECTOR_DB_DIR = os.getenv("VECTOR_DB_DIR", "./vector_db")
# SYS-10: always the pipeline's own model -- no script-local override, so this can't
# drift from ChunkFAISSDatasource again. The dimension is read off the loaded model
# in main() rather than hardcoded here, so it always matches whatever
# EMBEDDING_MODEL_HF actually outputs.
EMBEDDING_MODEL = EMBEDDING_MODEL_HF
L1_INDEX_PATH = os.path.join(VECTOR_DB_DIR, "faiss_l1.index")
L2_INDEX_PATH = os.path.join(VECTOR_DB_DIR, "faiss_l2.index")

_FETCH_SQL = text("""
    SELECT
        a.articles_id,
        a.sitemap_id,
        a.extracted_text,
        s.headline,
        s.sources,
        s.category,
        s.posted_at
    FROM articles a
    JOIN sitemaps s ON a.sitemap_id = s.sitemap_id
    LEFT JOIN chunks c ON a.articles_id = c.article_id
    WHERE c.chunk_id IS NULL AND a.articles_id > :after_id
    ORDER BY a.articles_id
    LIMIT :lim
""")

_INSERT_SQL = text("""
    INSERT INTO chunks (
        sitemap_id, article_id, chunk_level, chunk_index, chunk_total,
        is_first_chunk, is_last_chunk, text_content, token_count,
        embedding_id, chunk_status
    ) VALUES (
        :sitemap_id, :article_id, :chunk_level, :chunk_index, :chunk_total,
        :is_first_chunk, :is_last_chunk, :text_content, :token_count,
        :embedding_id, :chunk_status
    )
""")


def _load_or_create_index(path: str, dim: int):
    import faiss
    if os.path.exists(path):
        logger.info("Loading FAISS index from %s", path)
        return faiss.read_index(path)
    logger.info("Creating new FAISS index at %s", path)
    return faiss.IndexFlatIP(dim)  # inner product; vectors are L2-normalized → cosine sim


def _save_indexes(l1_idx, l2_idx) -> None:
    import faiss
    os.makedirs(VECTOR_DB_DIR, exist_ok=True)
    faiss.write_index(l1_idx, L1_INDEX_PATH)
    faiss.write_index(l2_idx, L2_INDEX_PATH)
    logger.info("Saved indexes — L1: %d vectors, L2: %d vectors", l1_idx.ntotal, l2_idx.ntotal)


def _parse_paragraphs(raw) -> list:
    """Handle the List[str] stored as a String column (Python repr or JSON)."""
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, str):
        return []
    for loader in (json.loads, ast.literal_eval):
        try:
            result = loader(raw)
            if isinstance(result, list):
                return [str(p) for p in result if p]
        except Exception:
            continue
    # Last resort: treat the whole string as a single paragraph
    return [raw] if raw.strip() else []


def main() -> None:
    parser = argparse.ArgumentParser(description="Chunk and embed unprocessed articles")
    parser.add_argument("--batch-size", type=int, default=100, metavar="N",
                        help="Articles per batch (default: 100)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and chunk without writing to DB or FAISS")
    args = parser.parse_args()

    chunker = HierarchicalChunker()
    client = SQLAlchemyClient()

    if not args.dry_run:
        logger.info("Loading embedding model: %s", EMBEDDING_MODEL)
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(EMBEDDING_MODEL)
        embedding_dim = model.get_sentence_embedding_dimension()
        l1_idx = _load_or_create_index(L1_INDEX_PATH, embedding_dim)
        l2_idx = _load_or_create_index(L2_INDEX_PATH, embedding_dim)
    else:
        model = l1_idx = l2_idx = None
        logger.info("[dry-run] Skipping model and FAISS index load")

    total_articles = 0
    total_chunks = 0
    # SYS-28: page by articles_id rather than relying solely on "no chunks row yet"
    # to shrink the result set. --dry-run never writes a chunks row, so without this
    # cursor the same LIMIT page would come back forever (real mode self-corrects
    # once it writes, but even there an article with empty extracted_text never
    # gets a chunks row and would otherwise resurface at the front of every future
    # batch for the rest of the run). Advances on every fetched row, including
    # skipped ones, so a stuck article can never block later ones.
    after_id = 0

    with client.get_session() as session:
        while True:
            rows = session.execute(_FETCH_SQL, {"lim": args.batch_size, "after_id": after_id}).fetchall()
            if not rows:
                break
            after_id = max(row.articles_id for row in rows)

            logger.info("Batch of %d articles", len(rows))

            l1_texts: list = []
            l2_texts: list = []
            batch: list = []  # chunk dicts in insertion order

            for row in rows:
                article_id, sitemap_id, raw_text, headline, sources, category, posted_at = row
                paragraphs = _parse_paragraphs(raw_text)
                if not paragraphs:
                    logger.warning("Article %d: empty extracted_text — skipping", article_id)
                    continue

                # SYS-27: HierarchicalChunker.chunk() takes a NewsDetailsDTO (+ optional
                # SitemapDTO) and returns ChunkDTOs, not a (paragraphs, dict) call
                # returning plain dicts -- this script predates that interface change.
                # meta_data carries posted_at through: chunker.py only derives it from
                # sitemap.timestamp when set, and falls back to meta_data["posted_at"]
                # otherwise, so the DB's own int yyyymmdd value passes through unchanged.
                news = NewsDetailsDTO(
                    sitemap_id=sitemap_id, extracted_text=paragraphs, reporter=None,
                    meta_data={"title": headline, "posted_at": posted_at},
                )
                sitemap = SitemapDTO(headline=headline, link="", sources=sources or "", category=category)
                for cd in chunker.chunk(news, sitemap):
                    # ChunkDTO has no article_id (the live pipeline's ChunkModel doesn't
                    # carry one either -- chunks.article_id is nullable and unused there);
                    # this script has always populated it from its own _FETCH_SQL row, so
                    # keep doing that here rather than dropping it.
                    entry = {
                        "sitemap_id": cd.sitemap_id, "article_id": article_id,
                        "chunk_level": cd.chunk_level, "chunk_index": cd.chunk_index,
                        "chunk_total": cd.chunk_total,
                        "is_first_chunk": cd.is_first_chunk, "is_last_chunk": cd.is_last_chunk,
                        "text_content": cd.text_content, "token_count": cd.token_count,
                    }
                    (l1_texts if cd.chunk_level == 1 else l2_texts).append(cd.text_content)
                    batch.append(entry)

            if not batch:
                break

            if args.dry_run:
                logger.info("[dry-run] Would embed %d L1 + %d L2 chunks", len(l1_texts), len(l2_texts))
                total_articles += len(rows)
                total_chunks += len(batch)
                continue

            # ---- embed ------------------------------------------------- #
            l1_start = l1_idx.ntotal
            l2_start = l2_idx.ntotal

            if l1_texts:
                vecs = model.encode(l1_texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
                l1_idx.add(np.array(vecs, dtype=np.float32))

            if l2_texts:
                vecs = model.encode(l2_texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
                l2_idx.add(np.array(vecs, dtype=np.float32))

            # ---- assign embedding IDs ----------------------------------- #
            l1_cur = l2_cur = 0
            for c in batch:
                if c["chunk_level"] == 1:
                    c["embedding_id"] = f"l1:{l1_start + l1_cur}"
                    l1_cur += 1
                else:
                    c["embedding_id"] = f"l2:{l2_start + l2_cur}"
                    l2_cur += 1
                c["chunk_status"] = "embedded"

            # ---- persist ------------------------------------------------ #
            session.execute(_INSERT_SQL, batch)
            session.commit()
            _save_indexes(l1_idx, l2_idx)

            total_articles += len(rows)
            total_chunks += len(batch)
            logger.info("Progress: %d articles processed, %d chunks written", total_articles, total_chunks)

    logger.info("Done. %d articles → %d chunks.", total_articles, total_chunks)
    if not args.dry_run and l1_idx is not None:
        logger.info("Final FAISS: L1=%d, L2=%d vectors", l1_idx.ntotal, l2_idx.ntotal)


if __name__ == "__main__":
    main()
