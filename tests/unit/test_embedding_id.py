"""Tests for embedding ID assignment logic (mirrors backfill_chunks.py lines 187-195)."""
import pytest


def assign_embedding_ids(batch: list, l1_start: int, l2_start: int) -> list:
    l1_cur = l2_cur = 0
    for c in batch:
        if c["chunk_level"] == 1:
            c["embedding_id"] = f"l1:{l1_start + l1_cur}"
            l1_cur += 1
        else:
            c["embedding_id"] = f"l2:{l2_start + l2_cur}"
            l2_cur += 1
        c["chunk_status"] = "embedded"
    return batch


def make_chunk(level: int) -> dict:
    return {"chunk_level": level, "embedding_id": None, "chunk_status": "pending_embedding"}


class TestEmbeddingIdAssignment:
    def test_EI01_first_batch_ids_start_from_zero(self):
        batch = [make_chunk(1), make_chunk(1), make_chunk(2), make_chunk(2), make_chunk(2)]
        assign_embedding_ids(batch, 0, 0)
        l1 = [c for c in batch if c["chunk_level"] == 1]
        l2 = [c for c in batch if c["chunk_level"] == 2]
        assert l1[0]["embedding_id"] == "l1:0"
        assert l1[1]["embedding_id"] == "l1:1"
        assert l2[0]["embedding_id"] == "l2:0"
        assert l2[1]["embedding_id"] == "l2:1"
        assert l2[2]["embedding_id"] == "l2:2"

    def test_EI02_second_batch_continues_from_previous_counts(self):
        batch = [make_chunk(1), make_chunk(2), make_chunk(2)]
        assign_embedding_ids(batch, 2, 3)
        l1 = [c for c in batch if c["chunk_level"] == 1]
        l2 = [c for c in batch if c["chunk_level"] == 2]
        assert l1[0]["embedding_id"] == "l1:2"
        assert l2[0]["embedding_id"] == "l2:3"
        assert l2[1]["embedding_id"] == "l2:4"

    def test_EI03_l1_and_l2_counters_are_independent(self):
        batch = [make_chunk(2), make_chunk(1), make_chunk(2), make_chunk(1)]
        assign_embedding_ids(batch, 0, 0)
        l1_ids = [c["embedding_id"] for c in batch if c["chunk_level"] == 1]
        l2_ids = [c["embedding_id"] for c in batch if c["chunk_level"] == 2]
        assert l1_ids == ["l1:0", "l1:1"]
        assert l2_ids == ["l2:0", "l2:1"]

    def test_EI04_all_chunks_status_set_to_embedded(self):
        batch = [make_chunk(1), make_chunk(2), make_chunk(2)]
        assign_embedding_ids(batch, 0, 0)
        assert all(c["chunk_status"] == "embedded" for c in batch)

    def test_EI05_empty_batch_no_error(self):
        assert assign_embedding_ids([], 0, 0) == []

    def test_EI06_only_l1_chunks(self):
        batch = [make_chunk(1), make_chunk(1)]
        assign_embedding_ids(batch, 5, 0)
        assert batch[0]["embedding_id"] == "l1:5"
        assert batch[1]["embedding_id"] == "l1:6"

    def test_EI07_only_l2_chunks(self):
        batch = [make_chunk(2), make_chunk(2), make_chunk(2)]
        assign_embedding_ids(batch, 0, 10)
        assert batch[0]["embedding_id"] == "l2:10"
        assert batch[1]["embedding_id"] == "l2:11"
        assert batch[2]["embedding_id"] == "l2:12"
