"""
SYS-19 against a live PostgreSQL: a poison article (Gemini response never parses)
must stop being re-selected by get_articles_pending_extraction after
KNOWLEDGE_EXTRACT_MAX_ATTEMPTS failures, instead of burning one Gemini call per run
forever. Also confirms the atomic per-article transaction: a crash partway through
processing one article's entities rolls back that article's writes entirely (no
partial entity_mentions) without blocking a good article in the same batch.

Gemini itself is mocked (no network, no API key needed, no real quota consumed) --
only the DB interaction is live.
"""
from unittest.mock import MagicMock

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402


@pytest.fixture
def client():
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    c = SQLAlchemyClient()
    try:
        with c.get_session() as s:
            s.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    return c


def _insert_article(client, link, extracted_text="Some article text about the economy.", posted_at=20991231):
    # posted_at defaults far in the future: the test DB carries leftover pending
    # fixture rows from other tests (documented trap -- "integration suite needs a
    # clean newsaggregator_test"), and get_articles_pending_extraction orders by
    # (attempts ASC, posted_at DESC), so this guarantees our rows sort first among
    # equal-attempts rows regardless of what else is pending.
    with client.get_session() as s:
        row = s.execute(
            text(
                "INSERT INTO sitemaps (headline, link, sources, posted_at) "
                "VALUES ('t', :l, 'TEST', :posted_at) RETURNING sitemap_id"
            ),
            {"l": link, "posted_at": posted_at},
        ).fetchone()
        sitemap_id = row.sitemap_id
        s.execute(
            text(
                "INSERT INTO articles (sitemap_id, extracted_text, is_embedded, knowledge_extracted) "
                "VALUES (:sid, :txt, false, 0) RETURNING articles_id"
            ),
            {"sid": sitemap_id, "txt": extracted_text},
        )
        s.commit()
    return sitemap_id


def _cleanup(client, sitemap_ids):
    with client.get_session() as s:
        s.execute(text("DELETE FROM entity_mentions WHERE sitemap_id = ANY(:ids)"), {"ids": sitemap_ids})
        s.execute(text("DELETE FROM articles WHERE sitemap_id = ANY(:ids)"), {"ids": sitemap_ids})
        s.execute(text("DELETE FROM sitemaps WHERE sitemap_id = ANY(:ids)"), {"ids": sitemap_ids})
        s.commit()


class TestPoisonArticleDropsOutAfterMaxAttempts:
    def test_exhausted_article_is_excluded_from_the_pending_query(self, client):
        """SYS-19's exact "Done when": once knowledge_extract_attempts reaches the
        limit, get_articles_pending_extraction must not return it. Verified directly
        against the real query rather than by looping extract_all() batch_size=1
        calls -- the test DB carries other genuinely-pending fixture rows (documented
        trap) with similarly future-dated posted_at, which makes which specific row a
        size-1 batch picks non-deterministic. This is what actually needs a real DB;
        the attempt-recording wiring itself is already covered above and in the
        mocked unit tests."""
        from newscrawler.core.constants import KNOWLEDGE_EXTRACT_MAX_ATTEMPTS
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_knowledge_data_source import (
            SQLAlchemyKnowledgeDataSource,
        )

        sitemap_id = _insert_article(client, "http://sys19.test/exhausted")
        try:
            ds = SQLAlchemyKnowledgeDataSource(client)
            with client.get_session() as s:
                article_id = s.execute(
                    text("SELECT articles_id FROM articles WHERE sitemap_id = :id"), {"id": sitemap_id}
                ).scalar()

            pending_before = {a["article_id"] for a in ds.get_articles_pending_extraction(1000000)}
            assert article_id in pending_before, "must start out eligible"

            for _ in range(KNOWLEDGE_EXTRACT_MAX_ATTEMPTS):
                ds.record_extraction_failure(article_id, "simulated poison response")

            with client.get_session() as s:
                row = s.execute(
                    text("SELECT knowledge_extract_attempts FROM articles WHERE articles_id = :id"),
                    {"id": article_id},
                ).fetchone()
            assert row.knowledge_extract_attempts == KNOWLEDGE_EXTRACT_MAX_ATTEMPTS

            pending_after = {a["article_id"] for a in ds.get_articles_pending_extraction(1000000)}
            assert article_id not in pending_after, "SYS-19: exhausted article must not be re-selected"
        finally:
            _cleanup(client, [sitemap_id])


class TestTransientApiFailureDoesNotRetireTheQueue:
    def test_simulated_three_run_outage_leaves_the_article_still_selectable(self, client):
        """OPS-09 (#63) Done-when, against a real DB: a Gemini call that raises
        (network error/5xx/timeout/rate-limit -- the API call itself never returned
        a usable response) must leave knowledge_extract_attempts untouched across
        repeated runs, unlike SYS-19's poison-pill case above where a response WAS
        received but couldn't be used. Three consecutive extract_all() calls
        simulating an outage must not retire the article."""
        from newscrawler.core.knowledge_extractor import GeminiTransientError, KnowledgeExtractor
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_knowledge_data_source import (
            SQLAlchemyKnowledgeDataSource,
        )
        from newscrawler.core.entity_normalizer import EntityNormalizer

        sitemap_id = _insert_article(client, "http://ops09.test/outage")
        try:
            ds = SQLAlchemyKnowledgeDataSource(client)
            with client.get_session() as s:
                article_id = s.execute(
                    text("SELECT articles_id FROM articles WHERE sitemap_id = :id"), {"id": sitemap_id}
                ).scalar()

            class Outage:
                name, priced = "gemini-test", False

                def complete(self, prompt):
                    raise GeminiTransientError("503 Service Unavailable (simulated)")

            for run in range(3):
                kx = KnowledgeExtractor(ds, provider=Outage(), daily_limit=1400, batch_size=1000, allow_peak=True)

                processed = kx.extract_all()
                assert processed == 0, f"run {run}: nothing should have been extractable during the outage"

            with client.get_session() as s:
                row = s.execute(
                    text("SELECT knowledge_extract_attempts, last_extract_error FROM articles WHERE articles_id = :id"),
                    {"id": article_id},
                ).fetchone()
            assert row.knowledge_extract_attempts == 0, (
                "a transient API failure must never increment knowledge_extract_attempts"
            )
            assert row.last_extract_error is None

            pending = {a["article_id"] for a in ds.get_articles_pending_extraction(1000000)}
            assert article_id in pending, "the article must still be selectable after the outage"
        finally:
            _cleanup(client, [sitemap_id])


class TestAtomicRollbackOnMidArticleFailure:
    def test_a_crash_mid_article_leaves_no_partial_mentions_but_does_not_block_others(self, client, monkeypatch):
        # Distinct posted_at (both still far-future) makes fetch order deterministic:
        # ORDER BY attempts ASC, posted_at DESC means "bad" (higher) is always
        # processed before "good" (lower), matching call_state's assumption below.
        bad_id = _insert_article(client, "http://sys19.test/bad", posted_at=20991231)
        good_id = _insert_article(client, "http://sys19.test/good", posted_at=20991230)
        try:
            from newscrawler.core.knowledge_extractor import KnowledgeExtractor
            from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_knowledge_data_source import (
                SQLAlchemyKnowledgeDataSource,
            )
            from newscrawler.core.entity_normalizer import EntityNormalizer

            ds = SQLAlchemyKnowledgeDataSource(client)
            import json
            from newscrawler.core.extraction_provider import Completion

            # First article: two persons, the second of which is malformed (a bare
            # string) mixed with entities that DO parse -- but real crash comes from
            # get_l1_chunk_id_for_article raising to simulate a genuine mid-write DB
            # error after the first entity's upsert already ran in the same session.
            call_state = {"n": 0}

            def fake_gemini(text_):
                call_state["n"] += 1
                if call_state["n"] == 1:
                    return {"persons": [{"name": "Bad Article Person"}], "event_type": "x"}
                return {"persons": [{"name": "Good Article Person"}], "event_type": "x"}

            class Scripted:
                name, priced = "gemini-test", False

                def complete(self, prompt):
                    return Completion(json.dumps(fake_gemini(prompt)))

            # SYS-39: a run now goes on until the queue is empty; this test is about its two rows,
            # not about whatever else is pending in the DB.
            monkeypatch.setattr("newscrawler.core.knowledge_extractor.KNOWLEDGE_MAX_PER_RUN", 2)
            # batch_size 2: exactly our two test rows -- see _insert_article's posted_at note
            kx = KnowledgeExtractor(ds, provider=Scripted(), daily_limit=1400, batch_size=2, allow_peak=True)

            original_get_chunk = ds.get_l1_chunk_id_for_article

            def flaky_get_chunk(sitemap_id):
                if call_state["n"] == 1:
                    raise RuntimeError("simulated mid-article DB failure")
                return original_get_chunk(sitemap_id)

            ds.get_l1_chunk_id_for_article = flaky_get_chunk

            processed = kx.extract_all()

            assert processed == 1, "the good article must still be processed"

            with client.get_session() as s:
                bad_mentions = s.execute(
                    text("SELECT COUNT(*) FROM entity_mentions WHERE sitemap_id = :id"), {"id": bad_id}
                ).scalar()
                bad_extracted = s.execute(
                    text("SELECT knowledge_extracted, knowledge_extract_attempts FROM articles WHERE sitemap_id = :id"),
                    {"id": bad_id},
                ).fetchone()
                good_extracted = s.execute(
                    text("SELECT knowledge_extracted FROM articles WHERE sitemap_id = :id"), {"id": good_id}
                ).scalar()

            assert bad_mentions == 0, "no partial entity_mentions from the crashed article"
            assert bad_extracted.knowledge_extracted == 0
            assert bad_extracted.knowledge_extract_attempts == 1
            assert good_extracted == 1, "the good article in the same batch must still succeed"

            # The rollback should have undone the entity insert too, not just the
            # mention -- both are in the same transaction.
            with client.get_session() as s:
                bad_entity_count = s.execute(
                    text("SELECT COUNT(*) FROM entities WHERE name = 'Bad Article Person'")
                ).scalar()
            assert bad_entity_count == 0, "the entity insert must roll back along with the mention"
        finally:
            _cleanup(client, [bad_id, good_id])
            with client.get_session() as s:
                s.execute(text("DELETE FROM entity_mentions WHERE entity_id IN "
                                "(SELECT entity_id FROM entities WHERE name IN "
                                "('Bad Article Person', 'Good Article Person'))"))
                s.execute(text("DELETE FROM entities WHERE name IN "
                                "('Bad Article Person', 'Good Article Person')"))
                s.commit()
