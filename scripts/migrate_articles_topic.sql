-- SYS-37 (#121): the probe's topic per article.
--   topic            one of newscrawler/core/filter_rubric.py TOPICS_NEWS
--                    (markets, macro_policy, corporate, commodities_energy, consumer,
--                     politics_government, law_crime, disaster_accident, international,
--                     tech_science, health_education, other_news); NULL for rows saved
--                    before the probe -- scripts/train_importance_probe.py --backfill fills them.
--   topic_confidence the topic head's probability of that class among the news classes.
-- The ORM (newscrawler/infrastructure/datasource/dataflow/write/sqlalchemy/table.py)
-- declares the same two columns; keep them in sync by hand.
--
-- Usage (or scripts/migrate.py, which records it in schema_migrations):
--   psql -U postgres -d newsaggregator -f scripts/migrate_articles_topic.sql

ALTER TABLE articles ADD COLUMN IF NOT EXISTS topic TEXT;
ALTER TABLE articles ADD COLUMN IF NOT EXISTS topic_confidence REAL;

CREATE INDEX IF NOT EXISTS idx_articles_topic ON articles(topic);
