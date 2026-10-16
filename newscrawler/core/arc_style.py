"""How a story arc's back-story reads: a story, or a date-by-date chronicle (SYS-156/159/160, tracker #336).

The owner's read of the SYS-150 replay: "the end paragraph is just spitting out
the arcs, there's no continuity in the story development". 69% of the latar
sentences were "Pada d/m, ..." and 13 of 19 latar held three or more dates
(.10x/reviews/2026-10-14-arc-writing-research.md). These are the measurements
of that, defined once: `story_arc.parse` refuses on them (SYS-156, SYS-159) and
the replay reports them (SYS-160), so the gate and the number agree.

- `date_led(sentence)`: the sentence opens on a date ("Pada 3/10, ...", "Sebelumnya,
  pada Rabu (24/9) ...", "Pada tanggal 3 Oktober, ...", "24/9: ...") or carries "pada <date>"
  anywhere.
- `time_anchors(text)`: the past times the text names -- each calendar date, and each relative
  phrase ("awal Oktober", "pekan lalu", "Sabtu lalu") not opened by "sejak" (SYS-164: since SYS-154
  asks for relative time, a chronicle can be written without one calendar date). "Sejak awal
  Oktober" and "sejak September" frame the story; they are not stops on its timeline. A calendar
  date after "sejak" ("Sejak 15/9") is still an anchor.
- `opens_on_time(sentence)`: the sentence opens on a time anchor; `time_led`: date-led, or that.
- `repeated_opening(text)`: the first word two sentences share, or None.
- `non_events(text)`: the process verbs that report talk about an event as an
  event ("dibahas", "disebut", "dikabarkan", "ditanggapi").
- `tied_to_today(latar, judul, hari_ini)`: the back-story's first sentence
  frames today's news -- it does not open on a time anchor, and it shares a
  content word with the judul or hari_ini, up to its affixes (`story_words`,
  `stems`; a name counts: "Ini gelombang kedua perombakan Polri" ties by
  "Polri", while its event words differ from today's "memutasi").
"""
import re
from typing import List, Optional

from newscrawler.core import newsletter_copy as copy
from newscrawler.core import story_words
from newscrawler.core.source_check import date_mentions, relative_phrases

_DAY = "|".join(copy.DAYS)
# What may stand before a time for the sentence to open on it: a time connector, prepositions ("Pada",
# "Pada tanggal", "Pada hari"), a day name before its date ("Sabtu (3/10)", "Sabtu, 3 Oktober").
_DAY_BEFORE = rf"(?:(?:{_DAY})\s*[(,]\s*)?"
_OPENS_ON_DATE = re.compile(rf"\s*(?:(?:sebelumnya|lalu|kemudian|selanjutnya|sementara itu|dan)\s*,?\s+)?"
                            rf"(?:(?:pada|sejak|per|hingga|tanggal|hari)\s+)*{_DAY_BEFORE}", re.IGNORECASE)
_PADA_DATE = re.compile(rf"\bpada\s+(?:(?:tanggal|hari)\s+)*{_DAY_BEFORE}$", re.IGNORECASE)
# "sejak" before a relative phrase ("sejak awal Oktober") or opening one ("sejak September", a table phrase of
# its own): either way a frame, not an anchor (SYS-164 rework: the second was counted, and refused by the tie).
_SEJAK_BEFORE = re.compile(r"\bsejak\s+$", re.IGNORECASE)
_SEJAK_OPENS = re.compile(r"sejak\b", re.IGNORECASE)
NON_EVENTS = re.compile(r"\b(?:dibahas|disebut|dikabarkan|ditanggapi)\b", re.IGNORECASE)


def sentences(text: str) -> List[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def _opens_on(sentence: str, positions: List[int]) -> bool:
    return bool(positions) and bool(_OPENS_ON_DATE.fullmatch(sentence[:min(positions)]))


def _is_frame(text: str, pos: int, phrase: str) -> bool:
    return bool(_SEJAK_BEFORE.search(text[:pos]) or _SEJAK_OPENS.match(phrase))


def _relative_anchors(text: str) -> List[tuple]:
    return [(pos, phrase) for pos, phrase in relative_phrases(text) if not _is_frame(text, pos, phrase)]


def opens_on_date(sentence: str) -> bool:
    return _opens_on(sentence, [pos for pos, *_ in date_mentions(sentence)])


def opens_on_time(sentence: str) -> bool:
    return _opens_on(sentence, [pos for pos, *_ in date_mentions(sentence)]
                     + [pos for pos, _ in _relative_anchors(sentence)])


def time_anchors(text: str) -> List[str]:
    text = text or ""
    found = [(pos, written) for pos, _, _, written in date_mentions(text)] + _relative_anchors(text)
    return [written for _, written in sorted(found)]


def date_led(sentence: str) -> bool:
    return opens_on_date(sentence) or any(_PADA_DATE.search(sentence[:pos]) for pos, *_ in date_mentions(sentence))


def time_led(sentence: str) -> bool:
    return date_led(sentence) or opens_on_time(sentence)


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
    return not opens_on_time(first) and bool(_families(today) & _families(story_words.content_words(first)))
