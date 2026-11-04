"""SYS-199 (#429) arm B (ADR-028): the trainer's data handling and mixed loss (no model, CPU torch)."""
import importlib.util
import json
import math
import os
import random

import torch

_spec = importlib.util.spec_from_file_location(
    "train_nli_armb", os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "experiments", "train_nli_armb.py"))
tr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tr)

ORDER = {"entailment": 0, "neutral": 1, "contradiction": 2}


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return str(path)


def test_pairs_are_binary_and_grouped_by_seed(tmp_path):
    rows = [{"seed_id": "hedge-1-ab", "premise": "P", "hypothesis": "H", "label": "faithful", "error_type": "hedge"},
            {"seed_id": "hedge-1-ab", "premise": "P", "hypothesis": "H2", "label": "unfaithful", "error_type": "hedge"}]
    got = tr.load_pairs(write_jsonl(tmp_path / "p.jsonl", rows))
    assert [(e["target"], e["source"], e["group"]) for e in got] == [(1, "pairs", "pairs:hedge-1-ab"),
                                                                     (0, "pairs", "pairs:hedge-1-ab")]


def test_indonli_labels_follow_the_models_order(tmp_path):
    rows = [{"premise_id": 7, "premise": "P", "hypothesis": "H", "label": x} for x in ("e", "n", "c")]
    order = {"entailment": 2, "neutral": 0, "contradiction": 1}
    got = tr.load_indonli(write_jsonl(tmp_path / "i.jsonl", rows), order)
    assert [e["target"] for e in got] == [2, 0, 1] and {e["group"] for e in got} == {"indonli:7"}


def test_the_dev_split_keeps_a_group_on_one_side():
    examples = [{"group": f"pairs:s{i}", "n": j} for i in range(400) for j in range(4)]
    train, dev = tr.split(examples, 0.1)
    assert {e["group"] for e in train}.isdisjoint({e["group"] for e in dev})
    assert 0.05 < len(dev) / len(examples) < 0.15
    assert tr.split(examples, 0.1) == (train, dev)          # deterministic


def test_binary_loss_is_minus_log_p_entail_or_its_complement():
    logits = torch.tensor([[2.0, 0.5, -1.0], [2.0, 0.5, -1.0]])
    p = torch.softmax(logits, dim=-1)[0]
    faithful = tr.mixed_loss(logits[:1], torch.tensor([1]), torch.tensor([True]), entail=0)
    unfaithful = tr.mixed_loss(logits[1:], torch.tensor([0]), torch.tensor([True]), entail=0)
    assert math.isclose(faithful.item(), -math.log(p[0].item()), rel_tol=1e-5)
    assert math.isclose(unfaithful.item(), -math.log(1 - p[0].item()), rel_tol=1e-5)


def test_binary_loss_uses_the_entailment_index_given():
    logits = torch.tensor([[0.1, 3.0, 0.2]])
    loss = tr.mixed_loss(logits, torch.tensor([1]), torch.tensor([True]), entail=1)
    assert math.isclose(loss.item(), -math.log(torch.softmax(logits, -1)[0, 1].item()), rel_tol=1e-5)


def test_three_class_rows_use_cross_entropy_and_mix_by_row():
    logits = torch.tensor([[0.3, 1.2, -0.4], [1.0, 0.0, 0.0]])
    targets = torch.tensor([2, 1])
    binary = torch.tensor([False, True])
    ce = torch.nn.functional.cross_entropy(logits[:1], targets[:1]).item()
    bce = -math.log(torch.softmax(logits[1], -1)[0].item())
    assert math.isclose(tr.mixed_loss(logits, targets, binary, entail=0).item(), (ce + bce) / 2, rel_tol=1e-5)


def test_batches_cover_every_example_once():
    examples = [{"i": i} for i in range(37)]
    got = tr.batches(examples, 8, random.Random(0))
    assert [len(b) for b in got] == [8, 8, 8, 8, 5]
    assert sorted(e["i"] for b in got for e in b) == list(range(37))
