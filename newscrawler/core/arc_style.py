"""How a story arc's back-story reads: a story, or a date-by-date chronicle (SYS-156/159/160, tracker #336).

The owner's read of the SYS-150 replay: "the end paragraph is just spitting out
the arcs, there's no continuity in the story development". 69% of the latar
sentences were "Pada d/m, ..." and 13 of 19 latar held three or more dates
(.10x/reviews/2026-10-14-arc-writing-research.md). These are the measurements
of that, defined once: `story_arc.parse` refuses on them (SYS-156, SYS-159) and
the replay reports them (SYS-160), so the gate and the number agree.

- `date_led(sentence)`: the sentence opens on a date ("Pada 3/10, ...", "Sebelumnya,
  pada Rabu (24/9) ...", "24/9: ...") or carries "pada <date>" anywhere.
- `repeated_opening(text)`: the first word two sentences share, or None.
- `non_events(text)`: the process verbs that report talk about an event as an
  event ("dibahas", "disebut", "dikabarkan", "ditanggapi").
- `tied_to_today(latar, judul, hari_ini)`: the back-story's first sentence
  frames today's news -- it does not open on a past date, and it shares a
  content word with the judul or hari_ini, up to its affixes (`story_words`,
  `stems`; a name counts: "Ini gelombang kedua perombakan Polri" ties by
  "Polri", while its event words differ from today's "memutasi").
"""
import re
from typing import List, Optional

from newscrawler.core import newsletter_copy as copy
from newscrawler.core import story_words
from newscrawler.core.source_check import date_mentions

_DAY = "|".join(copy.DAYS)
# What may stand before a date for the sentence to open on it: a time connector, a preposition, a day name.
_OPENS_ON_DATE = re.compile(rf"\s*(?:(?:sebelumnya|lalu|kemudian|selanjutnya|sementara itu|dan)\s*,?\s+)?"
                            rf"(?:(?:pada|sejak|per|hingga|tanggal)\s+)?(?:(?:{_DAY})\s*\(\s*)?", re.IGNORECASE)
_PADA_DATE = re.compile(rf"\bpada\s+(?:(?:{_DAY})\s*\(\s*)?$", re.IGNORECASE)
NON_EVENTS = re.compile(r"\b(?:dibahas|disebut|dikabarkan|ditanggapi)\b", re.IGNORECASE)


def sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def opens_on_date(sentence: str) -> bool:
    mentions = date_mentions(sentence)
    return bool(mentions) and bool(_OPENS_ON_DATE.fullmatch(sentence[:mentions[0][0]]))


def date_led(sentence: str) -> bool:
    return opens_on_date(sentence) or any(_PADA_DATE.search(sentence[:pos]) for pos, *_ in date_mentions(sentence))


def opening(sentence: str) -> str:
    match = story_words.WORD.search(sentence)
    return match.group(0).lower() if match else ""


def repeated_opening(text: str) -> Optional[str]:
    seen = set()
    for sentence in sentences(text):
        word = opening(sentence)
        if word and word in seen:
            return word
        seen.add(word)
    return None


def non_events(text: str) -> List[str]:
    return [m.group(0).lower() for m in NON_EVENTS.finditer(text or "")]


_PREFIXES = ("meng", "meny", "mem", "men", "me", "peng", "peny", "pem", "pen", "per", "pe", "ber", "be", "ter",
             "di", "ke", "se")
_NASAL = {"meng": "k", "meny": "s", "mem": "p", "men": "t", "peng": "k", "peny": "s", "pem": "p", "pen": "t"}
_SUFFIXES = ("nya", "kan", "an", "i")
MIN_STEM = 4


def stems(word: str) -> set:
    """The word and the stems it may carry under one Indonesian prefix and one suffix (nasal
    forms restored: menyepakati -> sepakat), each of at least MIN_STEM letters. Enough to tie
    "Kesepakatan ini ..." to today's "disepakati", or "Pelemahan" to "melemah" (the 2026-10-08
    re-run refused that BPIH frame); not a stemmer."""
    bases = {word} | {word[:-len(s)] for s in _SUFFIXES if word.endswith(s) and len(word) - len(s) >= MIN_STEM}
    out = set(bases)
    for base in bases:
        for prefix in _PREFIXES:
            rest = base[len(prefix):]
            if base.startswith(prefix) and len(rest) >= MIN_STEM:
                out.add(rest)
                if prefix in _NASAL:
                    out.add(_NASAL[prefix] + rest)
    return {s for s in out if len(s) >= MIN_STEM} or {word}


def _families(words) -> set:
    return {s for w in words for s in stems(w)}


def tied_to_today(latar: str, judul: str, hari_ini: str) -> bool:
    first = (sentences(latar) or [""])[0]
    if not first:
        return True
    today = story_words.story_content_words(judul, hari_ini)
    return not opens_on_date(first) and bool(_families(today) & _families(story_words.content_words(first)))
