-- SYS-18: rewrite articles.extracted_text from a Postgres array literal back to
-- prose.
--
-- The write path used to bind NewsDetailsModel.extracted_text (a List[str] of
-- paragraphs) straight to the `text` column. psycopg2 adapted the Python list as
-- an array literal, so every existing row reads as `{"para1","para2"}` (paragraphs
-- joined by `","`, inner double quotes escaped as `\"`) instead of the article
-- prose. The code fix (sql_alchemy_articles_data_source.py / table.py) now joins
-- paragraphs with a blank line before the value reaches the driver, matching the
-- format the trafilatura fallback already produces (crawler.py splits its own
-- output on "\n\n") -- this migration rewrites rows written before that fix.
--
-- Idempotent: only rows still in array-literal form are touched, so running this
-- twice is a no-op the second time.
--
-- Also re-queues extractions that ran against the mangled text (knowledge_extracted
-- reset to 0) so they get re-extracted from clean input; their existing
-- entity_mentions rows are left in place, not deleted.

BEGIN;

-- Match on a leading '{' generally, not just '{"' -- an array's first element is
-- only quoted when it needs escaping (spaces, commas, quotes, ...); a single plain
-- word (e.g. a section label like "CHINA" or "OPINI") is stored unquoted as
-- '{CHINA,"...",...}' and would otherwise be missed here.
WITH affected AS (
    SELECT articles_id
    FROM articles
    WHERE extracted_text LIKE '{%'
)
UPDATE articles
SET knowledge_extracted = 0,
    knowledge_extracted_at = NULL
WHERE knowledge_extracted = 1
  AND articles_id IN (SELECT articles_id FROM affected);

UPDATE articles
SET extracted_text = array_to_string(extracted_text::text[], E'\n\n')
WHERE extracted_text LIKE '{%';

COMMIT;

-- Verify: should return 0.
-- SELECT COUNT(*) FROM articles WHERE extracted_text LIKE '{%';
