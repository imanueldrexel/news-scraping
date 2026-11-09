"""OPS-04 (#52): the repair plan decides per (sitemap, level, index) key and never
touches a vector whose sitemap can still become an article."""
import importlib.util
import os
from types import SimpleNamespace

_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "repair_store_consistency.py",
)
_spec = importlib.util.spec_from_file_location("repair_store_consistency", _SCRIPT)
rsc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rsc)


def _doc(sid, lvl, idx):
    return SimpleNamespace(metadata={"sitemap_id": sid, "chunk_level": lvl, "chunk_index": idx}, page_content="x")


def test_docs_are_grouped_by_key_and_seed_docs_ignored():
    by_key = rsc.docs_by_key({"a": _doc(1, 1, 0), "b": _doc(1, 1, 0), "c": _doc(2, 2, 3),
                              "seed": SimpleNamespace(metadata={"seed": True})})
    assert dict(by_key) == {(1, 1, 0): ["a", "b"], (2, 2, 3): ["c"]}


def test_terminal_orphans_are_deleted_queued_ones_are_left_to_heal():
    docs = {"L1": {(1, 1, 0): ["t"], (2, 1, 0): ["q"], (3, 1, 0): ["gone"]}}
    p = rsc.plan(docs, {1: "terminal", 2: "queued"}, {})
    assert p["delete"] == {"L1": ["t", "gone"]}            # a missing sitemap row is terminal
    assert p["healing"] == {2} and p["insert"] == []


def test_a_duplicate_keeps_the_vector_the_chunk_row_points_at():
    docs = {"L2": {(5, 2, 0): ["old", "linked", "extra"]}}
    p = rsc.plan(docs, {5: "article"}, {(5, 2, 0): "linked"})
    assert sorted(p["delete"]["L2"]) == ["extra", "old"] and p["insert"] == []


def test_a_missing_chunk_row_is_rebuilt_from_the_first_vector():
    docs = {"L1": {(7, 1, 0): ["v1", "v2"]}}
    p = rsc.plan(docs, {7: "article"}, {})
    assert p["insert"] == [("L1", (7, 1, 0), "v1")] and p["delete"] == {"L1": ["v2"]}


def test_a_consistent_store_plans_nothing():
    docs = {"L1": {(9, 1, 0): ["v"]}, "L2": {(9, 2, 0): ["w"]}}
    p = rsc.plan(docs, {9: "article"}, {(9, 1, 0): "v", (9, 2, 0): "w"})
    assert p["delete"] == {} and p["insert"] == [] and p["counts"] == {"healing_sitemaps": 0, "orphan_chunk_rows_deleted": 0}


def test_repair_refuses_to_embed():
    import pytest
    with pytest.raises(RuntimeError):
        rsc._NoEmbeddings().embed_query("x")



def test_a_terminal_sitemaps_chunk_rows_go_with_its_vectors():
    """The 2026-09-26 regression: vectors deleted, chunk rows left pointing at
    nothing (chunks_not_in_faiss 0 -> 2,918)."""
    docs = {"L1": {(1, 1, 0): ["v"]}, "L2": {(1, 2, 0): ["w"]}}
    chunks = {(1, 1, 0): "v", (1, 2, 0): "w", (4, 1, 0): None}     # 4: chunks only, vectors already gone
    p = rsc.plan(docs, {1: "terminal", 4: "terminal"}, chunks)
    assert p["delete_chunk_sitemaps"] == {1, 4}
    assert p["counts"]["orphan_chunk_rows_deleted"] == 3


def test_invariant_no_deleted_vector_is_left_referenced_by_a_surviving_chunk_row():
    docs = {"L1": {(1, 1, 0): ["v1"], (2, 1, 0): ["v2"], (3, 1, 0): ["v3a", "v3b"]}}
    chunks = {(1, 1, 0): "v1", (2, 1, 0): "v2", (3, 1, 0): "v3b"}
    state = {1: "terminal", 2: "queued", 3: "article"}
    p = rsc.plan(docs, state, chunks)
    deleted = set(p["delete"].get("L1", []))
    surviving_refs = {eid for k, eid in chunks.items() if k[0] not in p["delete_chunk_sitemaps"]}
    assert not (deleted & surviving_refs)


def test_queued_and_articled_sitemaps_keep_their_chunk_rows():
    chunks = {(2, 1, 0): "q", (3, 1, 0): "a"}
    p = rsc.plan({}, {2: "queued", 3: "article"}, chunks)
    assert p["delete_chunk_sitemaps"] == set()
