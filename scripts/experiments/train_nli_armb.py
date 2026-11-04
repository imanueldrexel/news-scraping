"""SYS-199 (#429) arm B (ADR-028): fine-tune the arm A XNLI checkpoint on LLM-written pairs plus IndoNLI.

Runs in `venv-train/` (GPU torch) and imports nothing from `newscrawler`. Two example sources in one shuffled stream:
  - `pairs`: our training pairs (gen_nli_pairs.py JSONL, from articles the eval set never used). Binary target
    (faithful = 1), loss = binary cross-entropy on the softmax's entailment probability, so the 3-class head and
    `p_entail` keep their meaning for nli_check.HfScorer and the nli_shadow table.
  - `indonli`: IndoNLI train (Mahendra et al. 2021; e/n/c), 3-class cross-entropy, against forgetting general NLI.
A dev split (DEV_FRACTION of seeds / premises, by group so no seed is on both sides) picks the best checkpoint; the
eval set is never read here. The weights are saved with save_pretrained, with train_manifest.json beside them.

  venv-train\\Scripts\\python.exe scripts/experiments/train_nli_armb.py --pairs data/nli_train/train_pairs.jsonl ^
      --indonli data/indonli/train.jsonl --out models/nli/armb-<date>
Score the eval set afterwards in venv/: eval_nli.py --model models/nli/armb-<date>.
"""
import argparse
import hashlib
import json
import math
import os
import random
import sys
import time
from typing import Dict, List, Sequence, Tuple

BASE_MODEL = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
BASE_REVISION = "b5113eb38ab63efdd7f280f8c144ea8b13f978ce"      # arm A's checkpoint
INDONLI_LABELS = {"e": "entailment", "n": "neutral", "c": "contradiction"}
DEV_FRACTION = 0.05
MAX_LENGTH = 256                                                  # nli_check.MAX_LENGTH


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_pairs(path: str) -> List[dict]:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                p = json.loads(line)
                out.append({"premise": p["premise"], "hypothesis": p["hypothesis"], "source": "pairs",
                            "target": 1 if p["label"] == "faithful" else 0, "group": f"pairs:{p['seed_id']}",
                            "error_type": p["error_type"]})
    return out


def load_indonli(path: str, label_index: Dict[str, int]) -> List[dict]:
    """`label_index` maps entailment/neutral/contradiction to the model's logit index."""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                out.append({"premise": r["premise"], "hypothesis": r["hypothesis"], "source": "indonli",
                            "target": label_index[INDONLI_LABELS[r["label"]]], "group": f"indonli:{r['premise_id']}",
                            "error_type": None})
    return out


def is_dev(group: str, fraction: float = DEV_FRACTION) -> bool:
    """Deterministic by group, so every pair of a seed (or every hypothesis of a premise) is on one side."""
    return int(hashlib.md5(group.encode("utf-8")).hexdigest(), 16) % 10_000 < fraction * 10_000


def split(examples: Sequence[dict], fraction: float = DEV_FRACTION) -> Tuple[List[dict], List[dict]]:
    train, dev = [], []
    for e in examples:
        (dev if is_dev(e["group"], fraction) else train).append(e)
    return train, dev


def mixed_loss(logits, targets, binary, entail: int):
    """Mean over the batch. `binary` rows: -log p_entail (target 1) or -log(1 - p_entail) (target 0), from
    log-softmax so neither side underflows. Other rows: 3-class cross-entropy against `targets`."""
    import torch
    logp = torch.log_softmax(logits.float(), dim=-1)
    log_entail = logp[:, entail]
    others = [i for i in range(logp.shape[1]) if i != entail]
    log_not_entail = torch.logsumexp(logp[:, others], dim=-1)
    binary_loss = -torch.where(targets == 1, log_entail, log_not_entail)
    multi_loss = -logp.gather(1, targets.clamp(min=0).unsqueeze(1)).squeeze(1)
    return torch.where(binary, binary_loss, multi_loss).mean()


def batches(examples: Sequence[dict], size: int, rng: random.Random) -> List[List[dict]]:
    order = list(examples)
    rng.shuffle(order)
    return [order[i:i + size] for i in range(0, len(order), size)]


def encode(tokenizer, batch: Sequence[dict], device):
    import torch
    enc = tokenizer([e["premise"] for e in batch], [e["hypothesis"] for e in batch], truncation=True,
                    max_length=MAX_LENGTH, padding=True, return_tensors="pt").to(device)
    targets = torch.tensor([e["target"] for e in batch], device=device)
    binary = torch.tensor([e["source"] == "pairs" for e in batch], device=device)
    return enc, targets, binary


def evaluate(model, tokenizer, dev: Sequence[dict], entail: int, device, size: int = 64) -> dict:
    """Dev loss, pairs accuracy at p_entail 0.5 and IndoNLI 3-class accuracy."""
    import torch
    model.eval()
    total, n, pairs_ok, pairs_n, indo_ok, indo_n = 0.0, 0, 0, 0, 0, 0
    with torch.no_grad():
        for start in range(0, len(dev), size):
            batch = dev[start:start + size]
            enc, targets, binary = encode(tokenizer, batch, device)
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                logits = model(**enc).logits
            total += mixed_loss(logits, targets, binary, entail).item() * len(batch)
            n += len(batch)
            probs = torch.softmax(logits.float(), dim=-1)
            for row, e in zip(probs.tolist(), batch):
                if e["source"] == "pairs":
                    pairs_n += 1
                    pairs_ok += int((row[entail] >= 0.5) == (e["target"] == 1))
                else:
                    indo_n += 1
                    indo_ok += int(max(range(len(row)), key=row.__getitem__) == e["target"])
    model.train()
    return {"loss": total / max(n, 1), "pairs_acc": pairs_ok / max(pairs_n, 1), "indonli_acc": indo_ok / max(indo_n, 1)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--indonli", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--warmup", type=float, default=0.1)
    ap.add_argument("--evals-per-epoch", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0, help="smoke test: use only this many training examples")
    ap.add_argument("--train-embeddings", action="store_true", help="also train the word embeddings (needs > 6 GB)")
    args = ap.parse_args(argv)

    import torch
    import transformers
    from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup
    if not torch.cuda.is_available():
        print("no CUDA device: arm B trains on the GPU only (ADR-028)", file=sys.stderr)
        return 2
    device = torch.device("cuda")
    rng = random.Random(args.seed)
    torch.manual_seed(args.seed)

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, revision=BASE_REVISION)
    model = AutoModelForSequenceClassification.from_pretrained(BASE_MODEL, revision=BASE_REVISION).to(device)
    names = {int(i): str(n).lower() for i, n in model.config.id2label.items()}
    label_index = {n: i for i, n in names.items()}
    entail = label_index["entailment"]

    pairs, indonli = load_pairs(args.pairs), load_indonli(args.indonli, label_index)
    train, dev = split(pairs + indonli)
    if args.limit:
        rng.shuffle(train)
        train, dev = train[:args.limit], dev[:max(args.limit // 10, 32)]
    counts = {"train_pairs": sum(e["source"] == "pairs" for e in train), "train_indonli": sum(e["source"] == "indonli" for e in train),
              "dev_pairs": sum(e["source"] == "pairs" for e in dev), "dev_indonli": sum(e["source"] == "indonli" for e in dev)}
    print(counts)

    steps_per_epoch = math.ceil(len(train) / args.batch)
    total_steps = int(steps_per_epoch * args.epochs)
    eval_every = max(steps_per_epoch // args.evals_per_epoch, 1)
    if not args.train_embeddings:
        # the 250k x 768 word-embedding table is 192M of the 278M weights; its gradients and Adam state do not fit
        # in 6 GB next to the rest (OOM in the first optimizer step), and a few thousand pairs barely move it
        model.get_input_embeddings().requires_grad_(False)
    # long IndoNLI premises (multi-sentence, up to 256 tokens) ran out of memory in the forward pass at batch 16;
    # recomputing activations in the backward pass costs about a third more time and fits
    # (reentrant checkpointing backwards twice through DeBERTa's shared relative embeddings: RuntimeError)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    trainable = [p for p in model.parameters() if p.requires_grad]
    print(f"trainable parameters: {sum(p.numel() for p in trainable) / 1e6:.0f}M")
    optimizer = torch.optim.AdamW(trainable, lr=args.lr, weight_decay=0.01)
    scheduler = get_linear_schedule_with_warmup(optimizer, int(total_steps * args.warmup), total_steps)

    history = [{"step": 0, **evaluate(model, tokenizer, dev, entail, device)}]
    print(history[-1])
    best, step, started = history[0]["loss"], 0, time.time()
    os.makedirs(args.out, exist_ok=True)
    model.train()
    while step < total_steps:
        for batch in batches(train, args.batch, rng):
            enc, targets, binary = encode(tokenizer, batch, device)
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                logits = model(**enc).logits
            loss = mixed_loss(logits, targets, binary, entail)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()
            step += 1
            if step % eval_every == 0 or step == total_steps:
                history.append({"step": step, "train_loss": round(loss.item(), 4),
                                **evaluate(model, tokenizer, dev, entail, device)})
                print(history[-1], f"{time.time() - started:.0f}s", flush=True)
                if history[-1]["loss"] < best:
                    best = history[-1]["loss"]
                    model.save_pretrained(args.out, safe_serialization=True)
                    tokenizer.save_pretrained(args.out)
            if step >= total_steps:
                break

    if best == history[0]["loss"]:
        print("no step beat the base model on dev loss; nothing saved", file=sys.stderr)
        return 1
    best_step = min(history[1:], key=lambda h: h["loss"])
    manifest = {
        "ticket": "SYS-199 (#429) arm B, ADR-028", "base_model": BASE_MODEL, "base_revision": BASE_REVISION,
        "data": {"pairs": {"path": args.pairs, "sha256": sha256(args.pairs)},
                 "indonli": {"path": args.indonli, "sha256": sha256(args.indonli),
                             "url": "https://raw.githubusercontent.com/ir-nlp-csui/indonli/main/data/indonli/train.jsonl"}},
        "counts": counts, "dev_fraction": DEV_FRACTION, "max_length": MAX_LENGTH,
        "hyperparameters": {k: getattr(args, k) for k in ("epochs", "lr", "batch", "warmup", "seed", "limit",
                                                            "train_embeddings")},
        "precision": "bf16 autocast", "best": best_step, "history": history,
        "model_sha256": sha256(os.path.join(args.out, "model.safetensors")),
        "torch": torch.__version__, "transformers": transformers.__version__,
        "gpu": torch.cuda.get_device_name(0), "seconds": round(time.time() - started),
    }
    with open(os.path.join(args.out, "train_manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2)
    print("best", best_step, "->", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
