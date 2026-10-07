"""The keyword half of the search page (SYS-103, ADR-006).

A question's content words are matched against the L2 paragraphs' `fts_vector`:
a paragraph must hold the question's rare words (the anchors), and it is scored
by how much of the question it covers, each word weighted by how rare it is
(idf = ln(1/df)). "BI-Rate" (0.09% of paragraphs) then counts for far more than
"indonesia" (22%), and a function word ("apa", "soal") counts for nothing.

`terms` and `KeywordQuery.build` are pure. `DocFrequency` reads each word's share
of paragraphs: a common word from the planner's statistics (`pg_stats`, one
cheap read), any other word by an exact count, which is cheap because it is rare.
"""
import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence

from sqlalchemy import text

from newscrawler.core.story_words import STOPWORDS

MAX_TERMS = 12          # a 500-character question is not 60 lookups
ANCHOR_DF = 0.03        # a word in fewer than 3% of paragraphs selects them
NAME_DF = 0.10          # a name selects them up to 10% ("OJK", "Iran")
COUNT_CAP_DF = 0.10     # an exact count stops here: above it the weight barely moves
DF_TTL_S = 24 * 3600

QUESTION_WORDS = frozenset(
    "apa apakah bagaimana kenapa mengapa siapa kapan berapa mana dimana gimana seperti adakah benarkah "
    "terbaru terkini sekarang kini sepekan terakhir".split())
_TOKEN = re.compile(r"\w[\w.,-]*\w|\w", re.UNICODE)


class Term(NamedTuple):
    word: str           # lower case, as the 'simple' configuration indexes it
    name: bool


def terms(question: str) -> List[Term]:
    """The question's content words, in order, without duplicates, at most MAX_TERMS.
    A name is upper case ("KPK"), holds a digit ("2026"), or is capitalised past the first word."""
    out: List[Term] = []
    seen = set()
    for m in _TOKEN.finditer(question or ""):
        word = m.group(0).strip(".,-")
        low = word.lower()
        if len(low) < 2 or low in STOPWORDS or low in QUESTION_WORDS or low in seen or "_" in low:
            continue
        seen.add(low)
        name = word.isupper() or any(c.isdigit() for c in word) or (m.start() > 0 and word[0].isupper())
        out.append(Term(low, name))
        if len(out) == MAX_TERMS:
            break
    return out


def lexeme(word: str) -> str:
    """The word as a quoted tsquery operand (a bind value, never SQL text): 'bi-rate'."""
    return "'" + word.replace("'", "").replace("\\", "") + "'"


@dataclass(frozen=True)
class KeywordQuery:
    words: List[str]            # every word that occurs somewhere, question order
    weights: Dict[str, float]   # idf / sum of idf: a paragraph's coverage is the sum over its words
    anchors: List[str]          # a paragraph must hold `need` of these
    names: List[str]            # ... and one of these, when there are any
    need: int

    @classmethod
    def build(cls, question_terms: Sequence[Term], df: Dict[str, float]) -> Optional["KeywordQuery"]:
        """None when no word occurs anywhere (a question of typos, or of stop words only)."""
        kept = [t for t in question_terms if df.get(t.word, 0.0) > 0.0]
        if not kept:
            return None
        anchors = [t for t in kept if df[t.word] < (NAME_DF if t.name else ANCHOR_DF)]
        if not anchors:
            anchors = [min(kept, key=lambda t: df[t.word])]
        idf = {t.word: math.log(1.0 / min(df[t.word], 1.0)) for t in kept}
        total = sum(idf.values())
        if total <= 0:          # every word is in every paragraph: equal weights
            weights = {t.word: 1.0 / len(kept) for t in kept}
        else:
            weights = {w: v / total for w, v in idf.items()}
        return cls(words=[t.word for t in kept], weights=weights, anchors=[t.word for t in anchors],
                   names=[t.word for t in anchors if t.name], need=min(2, len(anchors)))


class DocFrequency:
    """Each word's share of L2 paragraphs, cached per process for DF_TTL_S.

    A word in the planner's most-common list takes its share from there (ANALYZE's sample
    over all chunk levels, within a fraction of a point of the exact L2 share). A word not
    in that list is rarer than its smallest entry and is counted exactly. Without
    statistics every word is counted. A failure raises; the caller drops the keyword half."""

    def __init__(self, client, ttl_s: float = DF_TTL_S, clock: Callable[[], float] = time.monotonic):
        self.client = client
        self.ttl_s = ttl_s
        self.clock = clock
        self._lock = threading.Lock()
        self._loaded_at: Optional[float] = None
        self._total = 0
        self._common: Dict[str, float] = {}
        self._counted: Dict[str, float] = {}

    def get(self, words: Sequence[str]) -> Dict[str, float]:
        # The database work runs outside the lock: two threads may count one word twice, harmlessly.
        with self._lock:
            fresh = self._loaded_at is not None and self.clock() - self._loaded_at < self.ttl_s
        if not fresh:
            self._reload()
        with self._lock:
            known = {w: self._lookup(w) for w in words}
        missing = [w for w in words if known[w] is None]
        if missing:
            counts = self._count(missing)
            with self._lock:
                self._counted.update(counts)
            known.update(counts)
        return known

    def _lookup(self, word: str) -> Optional[float]:
        if word in self._common:
            return self._common[word]
        return self._counted.get(word)

    def _reload(self) -> None:
        with self.client.get_session() as session:
            total = session.execute(text("SELECT COUNT(*) FROM chunks WHERE chunk_level = 2")).scalar() or 0
            row = session.execute(text(
                "SELECT most_common_elems::text::text[] AS elems, most_common_elem_freqs AS freqs "
                "FROM pg_stats WHERE tablename = 'chunks' AND attname = 'fts_vector'")).fetchone()
        common: Dict[str, float] = {}
        if row is not None and row.elems and row.freqs:
            common = dict(zip(row.elems, (float(f) for f in row.freqs)))   # trailing min/max/null shares unzipped
        with self._lock:
            self._total = int(total)
            self._common = common
            self._counted = {}
            self._loaded_at = self.clock()

    def _count(self, words: Sequence[str]) -> Dict[str, float]:
        """One round trip: each word's paragraph count, stopped at COUNT_CAP_DF of the total."""
        total = self._total
        if total <= 0:
            return {w: 0.0 for w in words}
        params = {"cap": max(1, int(total * COUNT_CAP_DF))}
        cols = []
        for i, w in enumerate(words):
            params[f"t{i}"] = lexeme(w)
            cols.append(f"(SELECT COUNT(*) FROM (SELECT 1 FROM chunks WHERE chunk_level = 2 "
                        f"AND fts_vector @@ to_tsquery('simple', :t{i}) LIMIT :cap) AS x{i})")
        with self.client.get_session() as session:
            row = session.execute(text("SELECT " + ", ".join(cols)), params).fetchone()
        return {w: int(n) / total for w, n in zip(words, row)}
