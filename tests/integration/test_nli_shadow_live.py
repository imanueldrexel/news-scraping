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


class _Exact:
    """p_entail 0.99 when the hypothesis (minus its dot) is in the premise, else 0.05 -- no model is loaded."""
    revision = "exact@1"

    def score(self, pairs):
        return [((0.99, 0.005, 0.005) if h.rstrip(".").lower() in p.lower() else (0.05, 0.5, 0.45)) for p, h in pairs]


def test_a_replayed_edition_writes_rows_and_is_byte_identical_without_nli(ds, monkeypatch, tmp_path):
    """Done-when (#439): the generator's edition path, NLI_SHADOW off then on, against the real table."""
    from types import SimpleNamespace

    from newscrawler.core import newsletter_generator as g
    from newscrawler.core import nli_shadow
    from newscrawler.core.story_arc import StoryArc

    arc = StoryArc(judul="Harga beras", hari_ini="Harga beras naik karena pasokan seret. Stok gudang menipis.",
                   latar="", agenda="", sekilas="", terkait=[0], tidak_terkait=[], alur=[], alur_items=[])
    article = {"sitemap_id": 11, "source": "KOMPAS", "headline": "Beras", "link": "http://x/11",
               "l1_text": "Harga beras naik karena pasokan seret."}

    class Edition(SimpleNamespace):
        words, utama, sekilas, editor_fallback = 12, 1, 0, False

        def stats(self):
            return {"built": True}

    def edition():
        cand = SimpleNamespace(id=7, cluster={"articles": [article]})
        return Edition(markdown="# Rangkuman\n\nHarga beras naik karena pasokan seret.\n",
                       trace={"candidates": [cand], "arcs": [{"id": 7, "arc": arc, "timeline": []}]})

    monkeypatch.setattr(nli_shadow, "default_scorer", lambda name: _Exact())
    out = {}
    for on in (False, True):
        monkeypatch.setattr(g, "NLI_SHADOW", on)
        gen = g.NewsletterGenerator.__new__(g.NewsletterGenerator)
        gen.ds = ds
        gen.build_edition = lambda plan: edition()
        folder = tmp_path / ("on" if on else "off")
        folder.mkdir()
        _, path, _ = gen._write_edition(SimpleNamespace(date=DAY), str(folder / f"{DAY}.md"))
        out[on] = (open(path, "rb").read(), [r.p_entail for r in stored(ds)])
    assert out[True][0] == out[False][0]
    assert out[False][1] == []
    assert len(out[True][1]) == 3 and all(p is not None for p in out[True][1])


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
