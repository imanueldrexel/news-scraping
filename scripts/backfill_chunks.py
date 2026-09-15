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
    EMBEDDING_MODEL    nomic-embed-text

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
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

VECTOR_DB_DIR = os.getenv("VECTOR_DB_DIR", "./vector_db")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
EMBEDDING_DIM = 768
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
    WHERE c.chunk_id IS NULL
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
        l1_idx = _load_or_create_index(L1_INDEX_PATH, EMBEDDING_DIM)
        l2_idx = _load_or_create_index(L2_INDEX_PATH, EMBEDDING_DIM)
    else:
        model = l1_idx = l2_idx = None
        logger.info("[dry-run] Skipping model and FAISS index load")

    total_articles = 0
    total_chunks = 0

    with client.get_session() as session:
        while True:
            rows = session.execute(_FETCH_SQL, {"lim": args.batch_size}).fetchall()
            if not rows:
                break

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

                chunks = chunker.chunk(
                    paragraphs,
                    {"article_id": article_id, "sitemap_id": sitemap_id},
                )
                for c in chunks:
                    (l1_texts if c["chunk_level"] == 1 else l2_texts).append(c["text_content"])
                    batch.append(c)

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
