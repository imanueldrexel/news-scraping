"""SYS-198 (#428, ADR-024): nli_shadow through the real SQL on the test DB."""
from datetime import date

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed")
from sqlalchemy import text  # noqa: E402

DAY = date(2031, 1, 2)       # far from any real edition


def row(sentence, p=0.9):
    return {"edition_date": DAY, "story_id": 1, "field": "hari_ini", "sentence": sentence, "error_tags": "cause",
            "premise_ids": [11, 12], "best_premise": "kutipan", "p_entail": p, "p_neutral": 0.05,
            "p_contradict": 0.05, "model_revision": "stub@1"}


@pytest.fixture
def ds():
    from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_newsletter_data_source import \
        SQLAlchemyNewsletterDataSource
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    client = SQLAlchemyClient()
    try:
        with client.get_session() as s:
            s.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"Cannot connect to test DB: {exc}")
    source = SQLAlchemyNewsletterDataSource(client)
    yield source
    with client.get_session() as s:
        s.execute(text("DELETE FROM nli_shadow WHERE edition_date = :d"), {"d": DAY})
        s.commit()


def stored(ds):
    with ds.client.get_session() as s:
        return s.execute(text("SELECT sentence, p_entail, premise_ids FROM nli_shadow WHERE edition_date = :d "
                              "ORDER BY shadow_id"), {"d": DAY}).fetchall()


def test_rows_are_written_with_their_premise_ids(ds):
    assert ds.save_nli_shadow(DAY, [row("a"), row("b", None)]) == 2
    got = stored(ds)
    assert [r.sentence for r in got] == ["a", "b"] and got[1].p_entail is None and got[0].premise_ids == [11, 12]


def test_a_rerun_of_the_day_replaces_its_rows(ds):
    ds.save_nli_shadow(DAY, [row("a"), row("b")])
    ds.save_nli_shadow(DAY, [row("c")])
    assert [r.sentence for r in stored(ds)] == ["c"]


def test_rows_past_retention_are_dropped(ds):
    ds.save_nli_shadow(DAY, [row("old")])
    with ds.client.get_session() as s:
        s.execute(text("UPDATE nli_shadow SET created_at = NOW() - INTERVAL '91 days' WHERE edition_date = :d"),
                  {"d": DAY})
        s.commit()
        other = date(2031, 1, 3)
    ds.save_nli_shadow(other, [{**row("new"), "edition_date": other}])
    try:
        with ds.client.get_session() as s:
            left = s.execute(text("SELECT sentence FROM nli_shadow WHERE edition_date IN (:a, :b)"),
                             {"a": DAY, "b": other}).fetchall()
        assert [r.sentence for r in left] == ["new"]
    finally:
        with ds.client.get_session() as s:
            s.execute(text("DELETE FROM nli_shadow WHERE edition_date = :d"), {"d": other})
            s.commit()
