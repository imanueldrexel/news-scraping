"""SRC-50 (#162) / SYS-50 (#165): the queued-row rejection makes the live
category decision, per (source, category), and nothing else."""
import importlib.util
import os
from types import SimpleNamespace

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "reject_denied_categories.py",
)
_spec = importlib.util.spec_from_file_location("reject_denied_categories", _SCRIPT)
rdc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rdc)


def _row(sid, source, category, status="pending"):
    return SimpleNamespace(sitemap_id=sid, sources=source, category=category, crawl_status=status)


def test_denies_exactly_what_the_live_gate_denies_for_that_source():
    rows = [
        _row(1, "DETIK", "sehat"),          # DETIK's own soft leaf
        _row(2, "KONTAN", "sehat"),         # the same name, KONTAN's unsampled branch
        _row(3, "KOMPAS", "hiburan"),       # fleet vocabulary
        _row(4, "DETIK", "berita"),         # mixed bucket: the probe's call
        _row(5, "CNBC", "market"),          # a news desk
        _row(6, "DETIK", "F1"),             # case-insensitive, like the gate
    ]
    assert [r.sitemap_id for r in rdc.plan(rows)] == [1, 3, 6]


def test_the_verdict_is_cached_per_source_and_category_not_per_category():
    """A per-category cache would hand DETIK's verdict on `sehat` to KONTAN."""
    rows = [_row(1, "DETIK", "sehat"), _row(2, "KONTAN", "sehat"), _row(3, "DETIK", "sehat")]
    assert [r.sitemap_id for r in rdc.plan(rows)] == [1, 3]


def test_nothing_to_do_is_empty():
    assert rdc.plan([]) == []
