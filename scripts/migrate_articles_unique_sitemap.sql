-- DBT-07: enforce one `articles` row per sitemap_id.
--
-- Production has 617 duplicate rows across 437 sitemap_ids (up to 4 copies of one
-- article), caused by re-crawls before mark_sitemaps_attempted()/the cooldown
-- existed. Every downstream join on articles (newsletter clustering, knowledge
-- extraction, RAG, kb_query) double-counts these.
--
-- entity_mentions has TWO references into this duplicate set: sitemap_id (which is
-- identical across the duplicates and untouched by this migration) AND a hard FK
-- article_id -> articles.articles_id (no ON DELETE clause, so deleting a row that
-- still has entity_mentions pointing at it would abort with a FK violation). The
-- dedup below ranks, per sitemap_id, the row already referenced by entity_mentions
-- first, then the row with knowledge_extracted=1 (avoid re-paying Gemini), then the
-- lowest articles_id, and only ever deletes the losers -- so a referenced row is
-- never a delete candidate.
--
-- Safety check: if two duplicate rows for the same sitemap_id both have
-- entity_mentions referencing them, dropping either would break a FK and this
-- migration should stop rather than guess which to keep.
DO $$
DECLARE
    conflict_count INT;
BEGIN
    SELECT COUNT(*) INTO conflict_count
    FROM (
        SELECT a.sitemap_id
        FROM entity_mentions em
        JOIN articles a ON a.articles_id = em.article_id
        GROUP BY a.sitemap_id
        HAVING COUNT(DISTINCT em.article_id) > 1
    ) t;

    IF conflict_count > 0 THEN
        RAISE EXCEPTION
            'DBT-07: % sitemap_id(s) have entity_mentions referencing more than one duplicate articles row -- resolve manually before running this migration',
            conflict_count;
    END IF;
END $$;

BEGIN;

WITH ranked AS (
    SELECT
        a.articles_id,
        a.sitemap_id,
        ROW_NUMBER() OVER (
            PARTITION BY a.sitemap_id
            ORDER BY
                (EXISTS (SELECT 1 FROM entity_mentions em WHERE em.article_id = a.articles_id)) DESC,
                a.knowledge_extracted DESC,
                a.articles_id ASC
        ) AS rn
    FROM articles a
)
DELETE FROM articles
WHERE articles_id IN (
    SELECT articles_id FROM ranked WHERE rn > 1
)
-- Defense in depth: the ranking above already keeps any entity_mentions-referenced
-- row at rn=1, so this should never exclude anything -- but never delete one anyway.
AND NOT EXISTS (
    SELECT 1 FROM entity_mentions em WHERE em.article_id = articles.articles_id
);

CREATE UNIQUE INDEX IF NOT EXISTS articles_sitemap_id_uq ON articles(sitemap_id);

COMMIT;

-- Verify: should return 0.
-- SELECT COUNT(*) - COUNT(DISTINCT sitemap_id) FROM articles;
