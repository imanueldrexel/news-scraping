"""Which of a section's clusters tell one story (SYS-67 #215), decided by the summarizer.

The digest clusters short vectors with one global distance cut. A scandal covered
from many angles (a DPR hearing, a KPK statement, a photo, a denial) comes out as
five clusters and fills five of a section's eight slots. Neither the vectors nor
the headlines' words can recognise those five as one story: the angles' centroids
sit 0.23-0.45 apart while two unrelated KPK cases sit 0.20 apart, and the
scandal's own words are as frequent as "polisi" (both measured, EXPERIMENTS.md
"SYS-67"). A reader of the headlines can, so one call per section asks the model
which clusters are the same story, and `pick_shown` shows at most
NEWSLETTER_MAX_CLUSTERS_PER_STORY of each.

A failed or unusable answer raises `SummarizerError`: the caller keeps the
section as it was, and counts the failure.
"""
import json
import logging
import re
from typing import List, Optional, Sequence

from newscrawler.core.summarizer import Summarizer, SummarizerError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

HEADLINES_PER_CLUSTER = 4
HEADLINE_CHARS = 90

_PROMPT = (
    "Berikut daftar kelompok berita (nomor: beberapa judul, dipisah ||).\n"
    "Kelompokkan nomor yang membahas SATU PERISTIWA atau KASUS yang sama. Satu cerita mencakup SEMUA "
    "sudutnya: temuan awal, pemeriksaan, pernyataan atau bantahan pejabat, rapat DPR, langkah kementerian "
    "atau lembaga lain, dan perkembangan lanjutan, walaupun setiap judul membahas bagian yang berbeda dari "
    "kasus itu (misalnya skandal satu lapas: sidak, rapat DPR, KPK, bantahan kepala lapas, dan langkah "
    "kementerian adalah SATU cerita).\n"
    "Kasus yang berbeda harus terpisah, termasuk kasus yang kebetulan melibatkan lembaga atau orang yang "
    "sama (misalnya dua kasus KPK yang tidak berhubungan, atau KPK memeriksa seseorang dalam kasus lain). "
    "Setiap nomor muncul tepat sekali.\n"
    'Balas HANYA dengan JSON: {{"grup": [[0,3],[1],[2]]}}\n\n'
    "{clusters}"
)


def build_prompt(clusters: Sequence[dict]) -> str:
    lines = []
    for i, cluster in enumerate(clusters):
        headlines = " || ".join(a["headline"][:HEADLINE_CHARS] for a in cluster["articles"][:HEADLINES_PER_CLUSTER])
        lines.append(f"{i}: {headlines}")
    return _PROMPT.format(clusters="\n".join(lines))


def parse_groups(answer: str, n: int) -> Optional[List[List[int]]]:
    """The model's groups as lists of indexes, or None unless the answer is
    JSON (a bare list or {"grup": [...]}, possibly fenced or surrounded by text)
    in which every index 0..n-1 appears exactly once."""
    match = re.search(r"\{.*\}|\[.*\]", answer or "", re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    groups = data.get("grup") if isinstance(data, dict) else data
    if not isinstance(groups, list) or not all(isinstance(g, list) for g in groups):
        return None
    flat = [i for g in groups for i in g]
    if any(not isinstance(i, int) or isinstance(i, bool) for i in flat):
        return None
    if sorted(flat) != list(range(n)):
        return None
    return [g for g in groups if g]


def group_clusters(summarizer: Summarizer, clusters: Sequence[dict]) -> List[List[int]]:
    """Groups of cluster indexes that tell one story. Raises QuotaExhausted when
    the provider refuses, SummarizerError when the call fails or the answer is
    not a valid grouping."""
    if len(clusters) < 2:
        return [[i] for i in range(len(clusters))]
    answer = summarizer.summarize(build_prompt(clusters))
    groups = parse_groups(answer, len(clusters))
    if groups is None:
        raise SummarizerError(f"unusable story grouping: {answer[:120]!r}")
    return groups


def pick_shown(ranked: Sequence[dict], groups: Sequence[Sequence[int]], per_story: int, cap: int) -> list:
    """`ranked` (best first) cut to `cap` clusters, taking at most `per_story`
    from each group. The order is kept; a group's later clusters make room for
    the next stories. `per_story` 0 means no limit."""
    group_of = {i: g for g, members in enumerate(groups) for i in members}
    taken: dict = {}
    shown = []
    for i, cluster in enumerate(ranked):
        if len(shown) == cap:
            break
        g = group_of.get(i, -1 - i)            # an index the model left out is its own story
        if per_story and taken.get(g, 0) >= per_story:
            continue
        taken[g] = taken.get(g, 0) + 1
        shown.append(cluster)
    return shown
