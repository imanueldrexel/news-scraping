"""The NLI shadow pass over an edition's story arcs (SYS-198 #428, ADR-024).

For each arc the edition kept, every sentence of its text fields is scored by
`nli_check` against the quotes the lexicon gates read (the `terkait` articles'
guard_text and the chosen alur items), and one `nli_shadow` row records the
sentence, the gate families it matches, and the verdict. Nothing here changes
the edition: `record` reads it after the file is written and swallows its own
failures. v1 hypothesis is the whole sentence; the stored sentence and premise
ids let SYS-199 re-score minimal propositions offline.
"""
import logging
import time
from datetime import date
from typing import Callable, Dict, List, Optional, Sequence

from newscrawler.core import causal_check, source_check
from newscrawler.core.nli_check import HfScorer, Scorer, best_verdict
from newscrawler.core.story_arc import StoryArc, item_source
from newscrawler.core.story_summary import guard_text, pick_articles

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

FIELDS = ("judul", "hari_ini", "latar", "agenda", "sekilas")


def gate_tags(sentence: str) -> Optional[str]:
    """The lexicon gate families `sentence` matches, comma-joined; None = no gate would route it (the residual)."""
    tags = []
    if causal_check._causal_matches(sentence):
        tags.append("cause")
    if causal_check._HEDGE.search(sentence):
        tags.append("hedge")
    if causal_check._DENIAL.search(sentence):
        tags.append("denial")
    if source_check.end_points(sentence):
        tags.append("end")
    if source_check.future_phrases(sentence):
        tags.append("plan")
    return ",".join(tags) or None


def arc_sentences(arc: StoryArc) -> List[tuple]:
    """(field, sentence) of every sentence of the arc's text fields."""
    return [(name, s.strip()) for name in FIELDS for s in causal_check.sentences(getattr(arc, name))
            if s.strip()]


def premises(arc: StoryArc, shown: Sequence[dict]) -> List[tuple]:
    """(sitemap_id, text) of the quotes the gates read: the terkait articles, then the chosen alur items."""
    return ([(shown[i]["sitemap_id"], guard_text(shown[i])) for i in arc.terkait]
            + [(t.sitemap_id, item_source(t)) for t in arc.alur_items])


def build_rows(edition, digest_date: date, scorer: Scorer, budget_s: float,
               clock: Callable[[], float] = time.monotonic) -> List[dict]:
    """One row per arc sentence; sentences left when the time budget is spent get no verdict."""
    by_id = {c.id: c for c in edition.trace.get("candidates", [])}
    started, rows, skipped = clock(), [], 0
    for entry in edition.trace.get("arcs") or []:
        arc, cand = entry.get("arc"), by_id.get(entry["id"])
        if arc is None or cand is None:
            continue
        shown = pick_articles(cand.cluster["articles"])
        quotes = premises(arc, shown)
        texts, ids = [t for _, t in quotes], [i for i, _ in quotes]
        for name, sentence in arc_sentences(arc):
            verdict = None
            if clock() - started <= budget_s:
                verdict = best_verdict(scorer, texts, sentence)
            else:
                skipped += 1
            rows.append({
                "edition_date": digest_date, "story_id": entry["id"], "field": name, "sentence": sentence,
                "error_tags": gate_tags(sentence), "premise_ids": ids,
                "best_premise": verdict.premise if verdict else None,
                "p_entail": verdict.p_entail if verdict else None,
                "p_neutral": verdict.p_neutral if verdict else None,
                "p_contradict": verdict.p_contradict if verdict else None,
                "model_revision": verdict.revision if verdict else None,
            })
    if skipped:
        logger.warning(f"NLI shadow: time budget of {budget_s:.0f}s spent, {skipped} sentences have no verdict")
    return rows


def record(edition, digest_date: date, save: Callable[[date, List[dict]], None], scorer: Optional[Scorer],
           budget_s: float) -> Dict[str, int]:
    """Score the edition's arcs and save the rows. Never raises: the edition is already written."""
    stats = {"sentences": 0, "scored": 0}
    try:
        if scorer is None:
            logger.warning("NLI shadow is on but NLI_MODEL is not set: nothing recorded")
            return stats
        rows = build_rows(edition, digest_date, scorer, budget_s)
        if rows:
            save(digest_date, rows)
        stats = {"sentences": len(rows), "scored": sum(r["p_entail"] is not None for r in rows)}
        logger.info(f"NLI shadow: {stats['scored']}/{stats['sentences']} arc sentences scored")
    except Exception:  # noqa: BLE001 -- shadow: nothing here may cost the edition
        logger.exception("NLI shadow failed")
    return stats


def default_scorer(model_name: str) -> Optional[Scorer]:
    return HfScorer(model_name) if model_name else None
