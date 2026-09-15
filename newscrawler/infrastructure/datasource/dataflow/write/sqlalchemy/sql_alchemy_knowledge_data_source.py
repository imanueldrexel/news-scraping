import logging
from datetime import date, datetime
from typing import Dict, List, Optional

from sqlalchemy import text

from newscrawler.infrastructure.datasource.dataflow.model.entity_model import (
    EntityMentionModel,
    EntityModel,
)
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SQLAlchemyKnowledgeDataSource:
    def __init__(self, client: SQLAlchemyClient):
        self.client = client

    # ── Article loading ──────────────────────────────────────────────────────

    def get_articles_pending_extraction(self, batch_size: int) -> List[dict]:
        """Returns up to batch_size articles where knowledge_extracted = 0."""
        sql = text("""
            SELECT a.articles_id, a.sitemap_id, a.extracted_text,
                   a.writer,
                   s.sources, s.posted_at, s.headline
            FROM articles a
            JOIN sitemaps s ON a.sitemap_id = s.sitemap_id
            WHERE a.knowledge_extracted = 0
            ORDER BY s.posted_at DESC
            LIMIT :batch_size
        """)
        with self.client.get_session() as session:
            rows = session.execute(sql, {"batch_size": batch_size}).fetchall()
        return [
            {
                "article_id":     row.articles_id,
                "sitemap_id":     row.sitemap_id,
                "extracted_text": row.extracted_text or "",
                "source":         row.sources or "",
                "posted_at":      row.posted_at,   # int YYYYMMDD
                "headline":       row.headline or "",
            }
            for row in rows
        ]

    def mark_article_extracted(self, article_id: int) -> None:
        sql = text("""
            UPDATE articles
            SET knowledge_extracted = 1,
                knowledge_extracted_at = NOW()
            WHERE articles_id = :article_id
        """)
        with self.client.get_session() as session:
            session.execute(sql, {"article_id": article_id})
            session.commit()

    # ── Entity persistence ───────────────────────────────────────────────────

    def upsert_entity(self, model: EntityModel) -> int:
        """Insert or update entity; always returns the entity_id."""
        sql = text("""
            INSERT INTO entities
                (name, normalized_name, entity_type, subtype, ticker,
                 first_seen_at, last_seen_at, mention_count, created_at, updated_at)
            VALUES
                (:name, :normalized_name, :entity_type, :subtype, :ticker,
                 :first_seen_at, :last_seen_at, 1, NOW(), NOW())
            ON CONFLICT (normalized_name, entity_type)
            DO UPDATE SET
                last_seen_at  = EXCLUDED.last_seen_at,
                mention_count = entities.mention_count + 1,
                updated_at    = NOW()
            RETURNING entity_id
        """)
        with self.client.get_session() as session:
            row = session.execute(sql, {
                "name":            model.name,
                "normalized_name": model.normalized_name,
                "entity_type":     model.entity_type,
                "subtype":         model.subtype,
                "ticker":          model.ticker,
                "first_seen_at":   model.first_seen_at,
                "last_seen_at":    model.last_seen_at,
            }).fetchone()
            session.commit()
        return row.entity_id

    def insert_entity_mention(self, model: EntityMentionModel) -> None:
        sql = text("""
            INSERT INTO entity_mentions
                (entity_id, sitemap_id, article_id, chunk_id,
                 context_snippet, event_type, posted_at, source, created_at)
            VALUES
                (:entity_id, :sitemap_id, :article_id, :chunk_id,
                 :context_snippet, :event_type, :posted_at, :source, NOW())
            ON CONFLICT (entity_id, sitemap_id) DO NOTHING
        """)
        with self.client.get_session() as session:
            session.execute(sql, {
                "entity_id":       model.entity_id,
                "sitemap_id":      model.sitemap_id,
                "article_id":      model.article_id,
                "chunk_id":        model.chunk_id,
                "context_snippet": model.context_snippet,
                "event_type":      model.event_type,
                "posted_at":       model.posted_at,
                "source":          model.source,
            })
            session.commit()

    def insert_alias(self, alias_name: str, normalized_alias: str, entity_id: int) -> None:
        sql = text("""
            INSERT INTO entity_aliases (alias_name, normalized_alias, entity_id)
            VALUES (:alias_name, :normalized_alias, :entity_id)
            ON CONFLICT (normalized_alias) DO NOTHING
        """)
        with self.client.get_session() as session:
            session.execute(sql, {
                "alias_name":       alias_name,
                "normalized_alias": normalized_alias,
                "entity_id":        entity_id,
            })
            session.commit()

    # ── Alias map ────────────────────────────────────────────────────────────

    def load_alias_map(self) -> Dict[str, int]:
        """Returns {normalized_alias: entity_id} for all known aliases."""
        sql = text("SELECT normalized_alias, entity_id FROM entity_aliases")
        with self.client.get_session() as session:
            rows = session.execute(sql).fetchall()
        return {row.normalized_alias: row.entity_id for row in rows}

    # ── API usage counter ────────────────────────────────────────────────────

    def get_today_api_call_count(self, api_name: str) -> int:
        sql = text("""
            SELECT call_count FROM api_usage_log
            WHERE log_date = CURRENT_DATE AND api_name = :api_name
        """)
        with self.client.get_session() as session:
            row = session.execute(sql, {"api_name": api_name}).fetchone()
        return row.call_count if row else 0

    def increment_api_call_count(self, api_name: str) -> None:
        sql = text("""
            INSERT INTO api_usage_log (log_date, api_name, call_count)
            VALUES (CURRENT_DATE, :api_name, 1)
            ON CONFLICT (log_date, api_name)
            DO UPDATE SET call_count = api_usage_log.call_count + 1
        """)
        with self.client.get_session() as session:
            session.execute(sql, {"api_name": api_name})
            session.commit()

    # ── Chunk lookup ─────────────────────────────────────────────────────────

    def get_l1_chunk_id_for_article(self, sitemap_id: int) -> Optional[int]:
        sql = text("""
            SELECT chunk_id FROM chunks
            WHERE sitemap_id = :sitemap_id AND chunk_level = 1
            LIMIT 1
        """)
        with self.client.get_session() as session:
            row = session.execute(sql, {"sitemap_id": sitemap_id}).fetchone()
        return row.chunk_id if row else None

    # ── kb_query support ─────────────────────────────────────────────────────

    def query_entity_mentions(
        self,
        entity_name: Optional[str] = None,
        ticker: Optional[str] = None,
        days: Optional[int] = None,
        from_date: Optional[date] = None,
        to_date: Optional[date] = None,
        event_type: Optional[str] = None,
        limit: int = 200,
    ) -> dict:
        """
        Returns a dict with:
          - entity: basic entity info
          - mentions: list of mention dicts (date-sorted, newest first)
          - co_occurrences: top co-mentioned entities
        """
        # ── Resolve entity_id ────────────────────────────────────────────────
        if ticker:
            entity_row = self._find_entity_by_ticker(ticker)
        else:
            entity_row = self._find_entity_by_name(entity_name)

        if not entity_row:
            return {"entity": None, "mentions": [], "co_occurrences": []}

        entity_id   = entity_row["entity_id"]
        from_date   = from_date or (
            date.fromordinal(date.today().toordinal() - days) if days else None
        )
        to_date = to_date or date.today()

        # ── Fetch mentions ───────────────────────────────────────────────────
        mentions_sql = text("""
            SELECT em.posted_at, em.source, s.headline, s.link,
                   em.event_type, em.context_snippet
            FROM entity_mentions em
            JOIN sitemaps s ON em.sitemap_id = s.sitemap_id
            WHERE em.entity_id = :entity_id
              AND (:from_date IS NULL OR em.posted_at >= :from_date)
              AND em.posted_at <= :to_date
              AND (:event_type IS NULL OR em.event_type = :event_type)
            ORDER BY em.posted_at DESC
            LIMIT :limit
        """)
        with self.client.get_session() as session:
            rows = session.execute(mentions_sql, {
                "entity_id":  entity_id,
                "from_date":  from_date,
                "to_date":    to_date,
                "event_type": event_type,
                "limit":      limit,
            }).fetchall()

        mentions = [
            {
                "posted_at":       row.posted_at,
                "source":          row.source,
                "headline":        row.headline,
                "link":            row.link,
                "event_type":      row.event_type,
                "context_snippet": row.context_snippet,
            }
            for row in rows
        ]

        # ── Co-occurring entities ────────────────────────────────────────────
        co_sql = text("""
            SELECT e2.name, e2.entity_type, COUNT(*) AS co_count
            FROM entity_mentions em1
            JOIN entity_mentions em2
                ON em1.sitemap_id = em2.sitemap_id
               AND em1.entity_id  != em2.entity_id
            JOIN entities e2 ON em2.entity_id = e2.entity_id
            WHERE em1.entity_id = :entity_id
              AND (:from_date IS NULL OR em1.posted_at >= :from_date)
              AND em1.posted_at <= :to_date
            GROUP BY e2.entity_id, e2.name, e2.entity_type
            ORDER BY co_count DESC
            LIMIT 10
        """)
        with self.client.get_session() as session:
            co_rows = session.execute(co_sql, {
                "entity_id": entity_id,
                "from_date": from_date,
                "to_date":   to_date,
            }).fetchall()

        co_occurrences = [
            {"name": r.name, "entity_type": r.entity_type, "count": r.co_count}
            for r in co_rows
        ]

        # ── Unique source count ──────────────────────────────────────────────
        source_count = len({m["source"] for m in mentions})

        return {
            "entity":         entity_row,
            "mentions":       mentions,
            "co_occurrences": co_occurrences,
            "total_mentions": len(mentions),
            "source_count":   source_count,
        }

    def _find_entity_by_ticker(self, ticker: str) -> Optional[dict]:
        sql = text("""
            SELECT entity_id, name, entity_type, subtype, ticker
            FROM entities WHERE ticker = :ticker LIMIT 1
        """)
        with self.client.get_session() as session:
            row = session.execute(sql, {"ticker": ticker.upper()}).fetchone()
        if not row:
            return None
        return {"entity_id": row.entity_id, "name": row.name,
                "entity_type": row.entity_type, "subtype": row.subtype,
                "ticker": row.ticker}

    def _find_entity_by_name(self, name: str) -> Optional[dict]:
        sql = text("""
            SELECT entity_id, name, entity_type, subtype, ticker
            FROM entities
            WHERE name ILIKE :pattern OR normalized_name = :normalized
            ORDER BY mention_count DESC
            LIMIT 1
        """)
        normalized = name.lower() if name else ""
        with self.client.get_session() as session:
            row = session.execute(sql, {
                "pattern":    f"%{name}%",
                "normalized": normalized,
            }).fetchone()
        if not row:
            return None
        return {"entity_id": row.entity_id, "name": row.name,
                "entity_type": row.entity_type, "subtype": row.subtype,
                "ticker": row.ticker}

    # ── Seed helpers ─────────────────────────────────────────────────────────

    def seed_aliases(self, seed_data: list) -> None:
        """Upserts canonical entities and their aliases from seed data."""
        from newscrawler.core.entity_normalizer import EntityNormalizer
        normalizer = EntityNormalizer()

        for entry in seed_data:
            today = date.today()
            model = EntityModel(
                name=entry["canonical_name"],
                normalized_name=normalizer.normalize(entry["canonical_name"]),
                entity_type=entry["entity_type"],
                subtype=entry.get("subtype"),
                ticker=entry.get("ticker"),
                first_seen_at=today,
                last_seen_at=today,
            )
            entity_id = self.upsert_entity(model)

            for alias in entry.get("aliases", []):
                norm_alias = normalizer.normalize(alias)
                self.insert_alias(alias, norm_alias, entity_id)
