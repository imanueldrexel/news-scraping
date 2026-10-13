"""Holding generated text to its sources: numbers, dates, subject (DBT-72 #344, ADR-017).

The one place a model's text is compared with the articles it was written from.
The summary (SYS-82), the editor's 60-second sentences (SYS-83), the story arcs
(SYS-148) and Tanya Berita's answers (SYS-99) all call these; none defines its own.

- `unsupported_number(text, source)`: the first number or date in `text` that
  the source does not state, or None. Numbers are compared by value (`values`):
  "Rp2.574.000" matches "Rp 2.574.000" and "2,574,000", "Rp1,5" never matches
  "Rp15" (SYS-87). A date counts as stated when the source names that day and
  month in any form (`_date_in`), whichever form the text wrote it in: "4/10",
  or "4 Oktober" / "4 Okt" (SYS-153: a written-out date used to be checked as
  the bare number 4, which any "4 persen" satisfied).
- `dates_in(text)`: the (day, month) of every date the text writes, in order --
  what the arcs' date rule compares with the timeline (SYS-148).
- `off_subject(judul, inti, related)`: the related articles that name none of a
  summary's subjects (SYS-80).

The month names come from `newsletter_copy` (the reader's tables), so a date is
read the way the newsletter writes one.
"""
import re
from typing import Dict, Iterable, List, Optional, Set, Tuple

from newscrawler.core import newsletter_copy as copy
from newscrawler.core import story_words

ANCHOR_MIN_JUDUL_WORDS = 2     # SYS-80: or a name; see off_subject

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_SHORT_DATE = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])")
# Longest names first, so "Agustus" is not read as "Agu" + "stus"; the \b keeps "Mei" out of "Meikarta".
_MONTH_WORDS = sorted({m.lower() for m in copy.MONTHS + copy.MONTHS_SHORT}, key=len, reverse=True)
_MONTH_OF = {m.lower(): k for k, m in enumerate(copy.MONTHS, 1)}
_MONTH_OF.update({m.lower(): k for k, m in enumerate(copy.MONTHS_SHORT, 1)})
# "24 September", "24 Sep 2026": the year is part of the date, not a number of its own. Not inside a
# word: "M2 Agustus 2026" is the money supply of August (replay 2026-09-24), not 2 August.
_LONG_DATE = re.compile(rf"(?<![\w.,])(\d{{1,2}})\s+({'|'.join(_MONTH_WORDS)})\b(?:\s+(\d{{4}}))?", re.IGNORECASE)


def _canonical(whole: str, fraction: str = "") -> str:
    whole, fraction = whole.lstrip("0") or "0", fraction.rstrip("0")
    return f"{whole},{fraction}" if fraction else whole


def values(number: str) -> Set[str]:
    """The values a written number can stand for, canonical ('2.574.000' ->
    {'2574000'}, '1,50' -> {'1,5'}), so separators may differ but the decimal
    position may not (SYS-87: 'Rp1,5 triliun' is not 'Rp15 triliun').
    Indonesian notation first ('.' thousands, ',' decimal). The English one is
    read where Indonesian cannot be ('2,574,000', '1.5') and also where both
    can ('1,500': 1,5 or 1500); '1.500' is 1500 only, as Indonesian prose writes it."""
    separators = re.findall(r"[.,]", number)
    if not separators:
        return {_canonical(number)}
    if len(set(separators)) == 2:                       # 2.574,5 / 2,574.5: the last one is the decimal point
        point = max(number.rfind("."), number.rfind(","))
        return {_canonical(re.sub(r"[.,]", "", number[:point]), number[point + 1:])}
    parts = number.split(separators[0])
    if len(parts) > 2:                                  # 2.574.000 / 2,574,000: thousands
        return {_canonical("".join(parts))}
    whole, fraction = parts
    if len(fraction) != 3 or not whole.strip("0"):      # 1,5 / 133,88 / 1.5 / 0,125: a decimal
        return {_canonical(whole, fraction)}
    if separators[0] == ".":
        return {_canonical(whole + fraction)}
    return {_canonical(whole + fraction), _canonical(whole, fraction)}


def _date_in(day: int, month: int, source: str) -> bool:
    """True when the source names the date `day/month`: as 4/10, 04/10/2026, or
    '4 Oktober' / '4 Okt'. The prompt asks for 'Minggu (4/10)', which an article
    may have written out. (A 'd/m' copied as it stands, say a score, passes too.)"""
    if re.search(rf"(?<!\d)0?{day}/0?{month}(?!\d)", source):
        return True
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return False
    names = f"(?:{copy.MONTHS[month - 1]}|{copy.MONTHS_SHORT[month - 1]})"
    return bool(re.search(rf"(?<!\d)0?{day}\s+{names}\b", source, re.IGNORECASE))


def _dates(text: str) -> List[Tuple[int, int, int, str]]:
    """(position, day, month, as written) of every date in `text`, both forms."""
    found = [(m.start(), int(m.group(1)), int(m.group(2)), m.group(0)) for m in _SHORT_DATE.finditer(text)]
    found += [(m.start(), int(m.group(1)), _MONTH_OF[m.group(2).lower()], m.group(0))
              for m in _LONG_DATE.finditer(text)]
    return sorted(found)


def dates_in(text: str) -> List[Tuple[int, int]]:
    """(day, month) of every date `text` writes -- '24/9', '24 September',
    '24 Sep 2026' -- in the order written. A 'd/m' whose month is not 1-12 (a
    score, '3/13') is not a date and is left out."""
    return [(day, month) for _, day, month, _ in _dates(text) if 1 <= month <= 12]


def without_dates(text: str) -> str:
    """`text` with every date (short or written out, with its year) blanked: what is
    left are the numbers to compare by value. Lets a caller name a number problem
    and a date problem in one field separately (SYS-148)."""
    return _LONG_DATE.sub(" ", _SHORT_DATE.sub(" ", text))


def unsupported_number(text: str, source: str, dates: Iterable[Tuple[int, int]] = ()) -> Optional[str]:
    """The first number in `text` that the source does not contain, or None.
    Numbers are compared by value (`values`). A date, short (4/10) or written
    out (4 Oktober, 4 Okt 2026), passes when the source names that date in any
    form, or when it is one of `dates` -- (day, month) pairs known to be right
    that no source text states, such as a timeline item's own date (SYS-148);
    they never make their numbers available. A date's day is never checked as
    a bare number (SYS-153)."""
    available = {value for number in _NUMBER.findall(source) for value in values(number)}
    known = set(dates)
    for _, day, month, written in _dates(text):
        if (day, month) not in known and not _date_in(day, month, source):
            return written
    for number in _NUMBER.findall(without_dates(text)):
        if not values(number) & available:
            return number
    return None


def off_subject(judul: str, inti: str, related: Dict[int, str]) -> Tuple[List[str], List[int]]:
    """(anchors, strays) for SYS-80 (#236). The anchors are the summary's names
    (`story_words.names` of judul + inti) that a related article mentions. A
    stray is a related article that mentions none of them and fewer than
    ANCHOR_MIN_JUDUL_WORDS of the judul's content words: it is not about the
    story's subject (2026-10-04: "10 Saham Paling Babak Belur, FORU Paling
    Parah" marked `terkait` under "Saham Haji Isam beragam", supplying a FORU
    bullet; it names neither Haji Isam nor PACK, and shares only "saham" with
    the judul). The judul's words let an article that names the subject in
    other words pass ("short selling" without "BEI"; "Perancis" for
    "Prancis"; replay 2026-10-05: names alone flagged ~15 related articles in
    22 refusals). No anchor, no check: a summary without a name an article
    states ("Harga emas naik") cannot be held to one."""
    vocabulary = {i: story_words.vocabulary(text) for i, text in related.items()}
    anchors = sorted(w for w in story_words.names(f"{judul}. {inti}") if any(w in v for v in vocabulary.values()))
    if not anchors:
        return [], []
    judul_words = set(story_words.content_words(judul))
    return anchors, [i for i, v in vocabulary.items()
                     if not v.intersection(anchors) and len(judul_words & v) < ANCHOR_MIN_JUDUL_WORDS]
