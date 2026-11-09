"""
SYS-20 (#41): entities.mention_count, first_seen_at and last_seen_at must equal
what entity_mentions says, whatever path a mention took: an alias hit, the same
entity listed twice in one article, a retried article, articles processed out
of date order, or a seeded entity nobody has mentioned yet.

Runs KnowledgeExtractor._process_extraction (Gemini is not called) against the
real SQLAlchemyKnowledgeDataSource and newsaggregator_test.
"""
import uuid
from datetime import date

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

from newscrawler.tools import store_repair  # noqa: E402

SOURCE = "SYS20"


def _recount_script():
    """The script under test: its own DRIFT_SQL is the selection (DBT-50 -- the
    test used to carry a private copy, so dropping a clause from the script's
    query left every test green)."""
    import importlib.util
    import os
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "scripts", "recount_entity_mentions.py")
    spec = importlib.util.spec_from_file_location("recount_entity_mentions", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def client():
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    c = SQLAlchemyClient()
    try:
        with c.get_session() as s:
            s.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    yield c
    with c.get_session() as s:
        s.execute(text("DELETE FROM entity_mentions WHERE source = :s"), {"s": SOURCE})
        s.execute(text("DELETE FROM entity_aliases WHERE normalized_alias LIKE 'sys20%'"))
        s.execute(text("DELETE FROM entities WHERE normalized_name LIKE 'sys20%'"))
        s.execute(text("DELETE FROM articles WHERE sitemap_id IN (SELECT sitemap_id FROM sitemaps WHERE sources=:s)"),
                  {"s": SOURCE})
        s.execute(text("DELETE FROM sitemaps WHERE sources = :s"), {"s": SOURCE})
        s.commit()


@pytest.fixture
def kb(client):
    from newscrawler.core.knowledge_extractor import KnowledgeExtractor
    from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_knowledge_data_source import (
        SQLAlchemyKnowledgeDataSource,
    )
    ds = SQLAlchemyKnowledgeDataSource(client)
    return ds, KnowledgeExtractor(ds, api_key="unused")


def _article(client, posted_at: int):
    with client.get_session() as s:
        sid = s.execute(text("INSERT INTO sitemaps (headline, link, sources, posted_at) "
                             "VALUES ('t', :l, :s, :p) RETURNING sitemap_id"),
                        {"l": f"https://sys20.test/{uuid.uuid4().hex}", "s": SOURCE, "p": posted_at}).scalar()
        aid = s.execute(text("INSERT INTO articles (sitemap_id, extracted_text) VALUES (:id, 'x') "
                             "RETURNING articles_id"), {"id": sid}).scalar()
        s.commit()
    return {"article_id": aid, "sitemap_id": sid, "posted_at": posted_at, "source": SOURCE,
            "extracted_text": "Sys20 Bank dan Sys20 Menteri bicara soal suku bunga."}


def _process(ds, extractor, meta, orgs=(), persons=()):
    extraction = {"organizations": [{"name": n} for n in orgs], "persons": [{"name": n} for n in persons],
                  "locations": [], "event_type": "policy"}
    with ds.atomic_extraction_session() as session:
        extractor._process_extraction(extraction, meta, session)
        session.commit()


def _entity(client, normalized):
    with client.get_session() as s:
        return s.execute(text("SELECT mention_count, first_seen_at, last_seen_at FROM entities "
                              "WHERE normalized_name = :n"), {"n": normalized}).fetchone()


def _drift(client):
    """The script's selection, narrowed to this test's entities by name."""
    with client.get_session() as s:
        rows = s.execute(store_repair.ENTITY_DRIFT_SQL).fetchall()
    return [r.name for r in rows if r.name.lower().startswith("sys20")]


def _no_drift(client):
    return _drift(client) == []


class TestMentionCounts:
    def test_an_alias_hit_counts(self, client, kb):
        """The alias path used to return before upsert_entity: mention written,
        count left at the seeded value."""
        from newscrawler.infrastructure.datasource.dataflow.model.entity_model import EntityModel
        ds, extractor = kb
        entity_id = ds.upsert_entity(EntityModel(name="Sys20 Bank Central", normalized_name="sys20 bank central",
                                                 entity_type="ORGANIZATION"))
        ds.insert_alias("SYS20BC", extractor.normalizer.normalize("SYS20BC"), entity_id)
        assert _entity(client, "sys20 bank central").mention_count == 0, "seeding is not a mention"
        extractor.alias_map = ds.load_alias_map()

        _process(ds, extractor, _article(client, 20260915), orgs=["SYS20BC"])

        row = _entity(client, "sys20 bank central")
        assert row.mention_count == 1
        assert row.first_seen_at == row.last_seen_at == date(2026, 9, 15)
        assert _no_drift(client)

    def test_the_same_entity_twice_in_one_article_counts_once(self, client, kb):
        ds, extractor = kb
        _process(ds, extractor, _article(client, 20260915), orgs=["Sys20 Bank", "SYS20 BANK"])
        assert _entity(client, extractor.normalizer.normalize("Sys20 Bank")).mention_count == 1
        assert _no_drift(client)

    def test_a_retried_article_does_not_count_again(self, client, kb):
        ds, extractor = kb
        meta = _article(client, 20260915)
        _process(ds, extractor, meta, persons=["Sys20 Menteri"])
        _process(ds, extractor, meta, persons=["Sys20 Menteri"])
        assert _entity(client, extractor.normalizer.normalize("Sys20 Menteri")).mention_count == 1
        assert _no_drift(client)

    def test_dates_move_outwards_whatever_the_processing_order(self, client, kb):
        """Extraction orders by posted_at DESC: the newest article comes first."""
        ds, extractor = kb
        for posted_at in (20260920, 20260910, 20260915):
            _process(ds, extractor, _article(client, posted_at), orgs=["Sys20 Bank"])
        row = _entity(client, extractor.normalizer.normalize("Sys20 Bank"))
        assert (row.mention_count, row.first_seen_at, row.last_seen_at) == (
            3, date(2026, 9, 10), date(2026, 9, 20))
        assert _no_drift(client)


class TestRecountScript:
    def test_it_repairs_drift_written_before_the_fix(self, client, kb, tmp_path, monkeypatch):
        import os
        ds, extractor = kb
        _process(ds, extractor, _article(client, 20260915), orgs=["Sys20 Bank"])
        with client.get_session() as s:
            s.execute(text("UPDATE entities SET mention_count = 5, last_seen_at = '2026-01-01' "
                           "WHERE normalized_name LIKE 'sys20%'"))
            s.execute(text("INSERT INTO entities (name, normalized_name, entity_type, first_seen_at, "
                           "last_seen_at, mention_count) VALUES ('Sys20 Seeded', 'sys20 seeded', "
                           "'ORGANIZATION', '2026-05-23', '2026-05-23', 1)"))
            s.commit()
        assert not _no_drift(client)

        mod = _recount_script()
        monkeypatch.setattr(store_repair, "BACKUP_DIR", str(tmp_path))

        assert mod.main(["--dry-run"]) == 0
        assert not _no_drift(client) and os.listdir(tmp_path) == []
        assert mod.main([]) == 0
        assert _no_drift(client)
        assert _entity(client, "sys20 seeded") == (0, None, None)
        assert len(os.listdir(tmp_path)) == 1


class TestRecountSelectsEachKindOfDrift:
    """DBT-50: one fixture per clause of the script's DRIFT_SQL. Each must be
    selected on its own and cleared by the repair."""

    @pytest.mark.parametrize("column, value", [
        ("mention_count", "7"),
        ("first_seen_at", "'2026-01-01'"),
        ("last_seen_at", "'2026-12-31'"),
    ])
    def test_a_single_drifting_column_is_selected_and_repaired(self, client, kb, tmp_path, monkeypatch,
                                                               column, value):
        ds, extractor = kb
        _process(ds, extractor, _article(client, 20260915), orgs=["Sys20 Bank"])
        assert _no_drift(client)
        with client.get_session() as s:
            s.execute(text(f"UPDATE entities SET {column} = {value} WHERE normalized_name LIKE 'sys20%'"))
            s.commit()
        assert _drift(client) == ["Sys20 Bank"], f"drift in {column} alone must be selected"

        mod = _recount_script()
        monkeypatch.setattr(store_repair, "BACKUP_DIR", str(tmp_path))
        assert mod.main([]) == 0
        assert _no_drift(client)


class TestAcrossRuns:
    def test_an_entity_met_again_in_a_later_run_counts_once_per_article(self, client):
        """Each extraction run builds a new extractor, whose alias_map does not
        know entities created by earlier runs, so the second run reaches
        upsert_entity's ON CONFLICT path. That path must not count."""
        from newscrawler.core.knowledge_extractor import KnowledgeExtractor
        from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_knowledge_data_source import (
            SQLAlchemyKnowledgeDataSource,
        )
        ds = SQLAlchemyKnowledgeDataSource(client)
        for posted_at in (20260915, 20260916):
            run = KnowledgeExtractor(ds, api_key="unused")
            _process(ds, run, _article(client, posted_at), orgs=["Sys20 Bank"])
        row = _entity(client, KnowledgeExtractor(ds, api_key="unused").normalizer.normalize("Sys20 Bank"))
        assert row.mention_count == 2
        assert _no_drift(client)
