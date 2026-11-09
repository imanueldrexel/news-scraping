"""SRC-54 (#177): which articles the requeue selects, and which vectors go with them."""
import importlib.util
import os
from types import SimpleNamespace

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "requeue_cascaded_articles.py",
)
_spec = importlib.util.spec_from_file_location("requeue_cascaded_articles", _SCRIPT)
rca = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rca)

A = "Paragraf pertama tentang laba bersih emiten naik tajam."
B = "Paragraf kedua tentang rencana dividen tahun depan."
C = "Paragraf ketiga menutup artikel dengan jadwal RUPS."
CASCADED = "\n\n".join([A + " " + B + " " + C, B + " " + C, C])
CLEAN = "\n\n".join([A, B, C])


def test_only_cascaded_bodies_are_selected():
    assert rca.select_cascaded([(3, CASCADED), (1, CLEAN), (2, None), (4, CASCADED)]) == [3, 4]


def _doc(sid):
    return SimpleNamespace(metadata={} if sid is None else {"sitemap_id": sid})


def test_every_vector_of_a_selected_sitemap_is_deleted_and_nothing_else():
    docstore = {"a": _doc(3), "b": _doc(3), "c": _doc("4"), "d": _doc(5), "seed": _doc(None)}
    assert sorted(rca.vector_ids_for(docstore, [3, 4])) == ["a", "b", "c"]
