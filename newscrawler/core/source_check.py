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
from datetime import date, timedelta
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


def date_mentions(text: str) -> List[Tuple[int, int, int, str]]:
    """(position, day, month, as written) of every date `text` writes, in order;
    a 'd/m' whose month is not 1-12 is left out (as `dates_in`). Where a date
    stands in a sentence is what makes it date-led (`arc_style`, SYS-160)."""
    return [found for found in _dates(text) if 1 <= found[2] <= 12]


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


def resolve(day: int, month: int, today: date) -> Optional[date]:
    """The calendar date a written day/month most likely means, seen from `today`: this year,
    or last year when that would be more than a month ahead. None for an impossible date."""
    for year in (today.year, today.year - 1):
        try:
            found = date(year, month, day)
        except ValueError:
            return None
        if found <= today + timedelta(days=31):
            return found
    return None


def _month_part(part: str, month: int, year: int) -> Tuple[date, date]:
    last = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)).day
    first, end = {"awal": (1, 10), "pertengahan": (11, 20), "akhir": (21, last)}[part.lower()]
    return date(year, month, first), date(year, month, end)


def _month_year(name: str, year: Optional[str], today: date) -> Tuple[int, int]:
    month = _MONTH_OF[name.lower()]
    return month, int(year) if year else today.year - (month > today.month)


def _previous_month(today: date) -> Tuple[int, int]:
    return (today.month - 1, today.year) if today.month > 1 else (12, today.year - 1)


def _whole_month(month: int, year: int) -> Tuple[date, date]:
    return _month_part("awal", month, year)[0], _month_part("akhir", month, year)[1]


def _part_of_month(m, today):
    part, name, which, year = m.group("part"), m.group("month"), (m.group("which") or "").lower(), m.group("year")
    if name:
        month, y = _month_year(name, year, today)
    elif which == "lalu":
        month, y = _previous_month(today)
    else:                                              # "awal bulan", "awal bulan ini"
        month, y = today.month, today.year
    return _month_part(part, month, y)


def _days_back(today: date, n: int, slack: int) -> Tuple[date, date]:
    """The days `n` days before `today`, `slack` days either way, never today itself."""
    return today - timedelta(days=n + slack), today - timedelta(days=max(n - slack, 1))


def _last_days(n: int):
    return lambda m, today: (today - timedelta(days=n), today - timedelta(days=1))


def _last_week(m, today):
    monday = today - timedelta(days=today.weekday())
    return monday - timedelta(days=7), monday - timedelta(days=1)


def _weekday_last(m, today):
    back = (today.weekday() - copy.DAYS.index(m.group("day").capitalize())) % 7 or 7
    return today - timedelta(days=back), today - timedelta(days=back)


_COUNT = {"satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5, "enam": 6, "tujuh": 7, "delapan": 8,
          "sembilan": 9, "sepuluh": 10, "sebelas": 11}
# A count no table can turn into days: matched so the shorter phrase inside it is not read, and left unread.
_VAGUE_COUNT = r"beberapa|sekian|belasan|puluhan|ratusan|\w+\s+(?:belas|puluh)"


def _count_ago(m, today) -> Optional[Tuple[date, date]]:
    """SYS-157 rework (#352): "tiga pekan lalu" is three weeks back, never "pekan lalu" (last week);
    "dua bulan lalu" is two calendar months back, never "bulan lalu". None for a vague count."""
    word = m.group("n").lower()
    n = _COUNT.get(word) or (int(word) if word.isdigit() else None)
    if not n:
        return None
    unit = m.group("unit").lower()
    if unit == "bulan":
        k = today.year * 12 + today.month - 1 - n
        return _whole_month(k % 12 + 1, k // 12)
    return _days_back(today, n, 1) if unit == "hari" else _days_back(today, 7 * n, 2 if n == 1 else 3)


_MONTH_NAME = "|".join(_MONTH_WORDS)
# SYS-157 (#352): the relative time phrases a story arc may write instead of a calendar date, each with the
# days it can mean, seen from the edition's date (None: matched, so nothing shorter inside it is read, but
# not turned into days). Where two start together the longer is read: "dua pekan lalu" is not "pekan lalu".
_RELATIVE = [
    (rf"(?P<part>awal|pertengahan|akhir)\s+(?:(?P<month>{_MONTH_NAME})\b(?:\s+(?P<year>\d{{4}}))?"
     rf"|bulan(?:\s+(?P<which>ini|lalu))?\b)", _part_of_month),
    (rf"sejak\s+(?P<month>{_MONTH_NAME})\b(?:\s+(?P<year>\d{{4}}))?",
     lambda m, today: _whole_month(*_month_year(m.group("month"), m.group("year"), today))),
    (r"bulan\s+lalu", lambda m, today: _whole_month(*_previous_month(today))),
    (r"dua\s+pekan\s+(?:terakhir|belakangan)", _last_days(14)),
    (r"(?:sepekan|seminggu)\s+(?:terakhir|belakangan)", _last_days(7)),
    (r"(?:sepekan|seminggu)\s+lalu", lambda m, today: _days_back(today, 7, 2)),
    (rf"(?P<n>{'|'.join(_COUNT)}|\d+|{_VAGUE_COUNT})\s+(?P<unit>hari|pekan|minggu|bulan)\s+lalu", _count_ago),
    (r"pekan\s+lalu|(?-i:minggu)\s+lalu", _last_week),
    (rf"(?P<day>{'|'.join(d for d in copy.DAYS if d != 'Minggu')}|(?-i:Minggu))\s+lalu", _weekday_last),
    (r"kemarin", lambda m, today: (today - timedelta(days=1), today - timedelta(days=1))),
]
_RELATIVE_EACH = [(re.compile(rf"\b(?:{pattern})\b", re.IGNORECASE), span) for pattern, span in _RELATIVE]


def _blank_dates(text: str) -> str:
    """`text` with every date blanked by as many spaces, so positions still point into `text`."""
    blank = lambda m: " " * len(m.group(0))  # noqa: E731
    return _LONG_DATE.sub(blank, _SHORT_DATE.sub(blank, text))


def _relative_matches(text: str) -> list:
    """(match, span function) of every relative time phrase in `text`, in order: leftmost first, then
    the longest of those starting together, and none inside another's text."""
    text = _blank_dates(text)
    matches = sorted(((m.start(), -m.end(), m, span) for pattern, span in _RELATIVE_EACH
                      for m in pattern.finditer(text)), key=lambda t: t[:2])
    found, taken = [], 0
    for start, neg_end, m, span in matches:
        if start >= taken:
            found.append((m, span))
            taken = -neg_end
    return found


def relative_phrases(text: str) -> List[Tuple[int, str]]:
    """(position, phrase as written) of every relative time phrase in `text`, whether or not its days
    can be told ("beberapa pekan lalu" is one): where a sentence names a past time without a calendar
    date (`arc_style`, SYS-164). No edition date is needed to find them."""
    return [(m.start(), m.group(0)) for m, _ in _relative_matches(text)]


def relative_times(text: str, today: date) -> List[Tuple[str, date, date]]:
    """(phrase as written, first day, last day) of every relative time phrase in `text` -- "awal
    Oktober", "akhir bulan lalu", "sejak September", "pekan lalu", "sepekan lalu", "dua pekan
    terakhir", "Kamis lalu", "kemarin", "tiga hari lalu" -- as the days it can mean seen from
    `today` (SYS-157 #352). A calendar date with its month ("24 September") is not one: `dates_in`
    reads those. The ranges, agreed in tests/unit/test_source_check.py:
      awal / pertengahan / akhir <bulan>   1-10 / 11-20 / 21-end of that month
      sejak <bulan>, bulan lalu            that whole month (where it began)
      sepekan lalu                         5-9 days before
      N pekan lalu (N >= 2)                7N days before, 3 days either way (dua pekan lalu: 11-17)
      N bulan lalu                         the whole calendar month N months back
      sepekan / dua pekan terakhir         the 7 / 14 days before
      pekan lalu                           the previous Monday-Sunday week
      <hari> lalu                          the last such weekday before today ("Minggu lalu" is a
                                           Sunday only with a capital M; "minggu lalu" is last week)
      kemarin; N hari lalu                 the day before; N days before, one day either way
    A longer phrase is never read as a shorter one inside it: "tiga pekan lalu" is not "pekan lalu",
    and a vague count ("beberapa pekan lalu", "dua puluh hari lalu") is not read at all (QA,
    2026-10-14). "sepekan sebelumnya", "dua hari sebelumnya" are not read: they count from the event
    the sentence just told, not from today (replay 2026-10-11, the Padang flood arc), and the prompt
    lets a sequence word stand without a source."""
    found = []
    for m, span in _relative_matches(text):
        days = span(m, today)
        if days:
            found.append((m.group(0), *days))
    return found


def relative_name(day: date, today: date) -> str:
    """The relative phrase for a past `day` seen from `today` that `relative_times` reads back as a
    span holding it: "kemarin", "pekan lalu" (the previous Monday-Sunday week), else "awal /
    pertengahan / akhir <bulan>". The story arcs show it beside each timeline item, so the model
    can write the time without a calendar date and the check accepts it (SYS-154/157)."""
    if day == today - timedelta(days=1):
        return "kemarin"
    first, last = _last_week(None, today)
    if first <= day <= last:
        return "pekan lalu"
    part = "awal" if day.day <= 10 else "pertengahan" if day.day <= 20 else "akhir"
    return f"{part} {copy.MONTHS[day.month - 1]}"


_ORDINAL_WORDS = {"kedua": 2, "ketiga": 3, "keempat": 4, "kelima": 5, "keenam": 6, "ketujuh": 7, "kedelapan": 8,
                  "kesembilan": 9, "kesepuluh": 10}
_ORDINAL = re.compile(rf"(?:\b(?P<before>[^\W\d_][\w-]*)\s+)?\b(?P<ordinal>{'|'.join(_ORDINAL_WORDS)}|ke-(?P<n>\d+))\b"
                      r"(?P<times>\s+kali(?:nya)?\b)?(?P<belah>\s+belah\b)?", re.IGNORECASE)
# What a collective "kedua"/"ketiga" ("both", "all three") follows: function words and adverbs ("Kini kelima
# tersangka ...", replay 2026-10-10). Time words stay nouns: "pekan kedua", "hari ketiga".
_NOT_A_NOUN = (story_words.STOPWORDS - {"hari", "tahun", "bulan", "pekan"}) | {
    "kini", "lalu", "kemudian", "akhirnya", "bahkan", "hanya", "sebanyak", "total", "seluruh", "sementara"}
# ... and verbs: "menahan kedua tersangka", "memeriksa ketiga saksi", "bersama kedua menteri" (QA, 2026-10-14).
# A me-/di-/ber- word is read as a verb, except the nouns listed here ("termin kedua", "rapat terbatas ketiga"
# stay claims: ter- is not read as a verb prefix). A noun missing from the list leaves its claim unchecked,
# as before SYS-158; a verb read as a noun would cost a retry, so the rule leans to collective.
_VERB = re.compile(r"(?:me|di|ber)[a-z]{3,}")
_PREFIXED_NOUNS = {"menteri", "menit", "menara", "media", "medali", "meja", "metode", "merek", "mesin", "diskusi",
                   "dialog", "direktur", "direksi", "dirut", "divisi", "dinas", "distrik", "dimensi", "berita",
                   "berkas"}
_SEKIAN = re.compile(r"\bkesekian\s+kali(?:nya)?\b", re.IGNORECASE)
_SERIES = re.compile(rf"\b(?P<n>dua|tiga|empat|lima|enam|tujuh|delapan|sembilan|sepuluh|\d+)\s+"
                     r"(?P<unit>hari|pekan|minggu|bulan|sesi|kuartal|tahun|kali)(?:\s+perdagangan)?\s+"
                     r"(?:beruntun|berturut-turut)\b", re.IGNORECASE)
_RECORD = re.compile(r"\b(?P<record>pertama\s+kali(?:nya)?|terendah|tertinggi)\s+sejak\s+", re.IGNORECASE)
_PART = r"(?:(?P<part>awal|pertengahan|akhir)\s+)?"
# The time a record runs from, whole, so "terendah sejak awal Maret" never licenses "terendah sejak awal tahun"
# (QA, 2026-10-14: the key used to be the one word after "sejak"). Else up to three words, to the next
# function word or punctuation (`_record_time`).
_RECORD_TIME = re.compile(
    rf"(?:(?P<day>\d{{1,2}})\s+)?{_PART}(?P<month>{_MONTH_NAME})\b(?:\s+(?P<year>\d{{4}}))?"
    rf"|(?P<dm>\d{{1,2}}/\d{{1,2}})(?:/(?P<dmyear>\d{{2,4}}))?"
    r"|(?:(?P<spanpart>awal|pertengahan|akhir)\s+)?(?P<span>tahun|bulan|pekan|minggu|kuartal|semester)\b"
    r"(?:\s+(?P<which>ini|lalu|\d{4}|[IVX]+\b|\d\b))?"
    r"|(?P<bare_year>\d{4})\b", re.IGNORECASE)
_SERIES_COUNT = {"dua": 2, "tiga": 3, "empat": 4, "lima": 5, "enam": 6, "tujuh": 7, "delapan": 8, "sembilan": 9,
                 "sepuluh": 10}


def _record_time(rest: str) -> Tuple[str, str]:
    """(as written, key) of the time a record runs from; `rest` is the text after its "sejak".
    "awal tahun ini" is keyed "awal tahun"; a month's or a day's year stays in the key (see
    `stated_claims`)."""
    m = _RECORD_TIME.match(rest)
    if m:
        if m.group("month"):
            parts = [m.group("day"), m.group("part"), m.group("month"), m.group("year")]
        elif m.group("dm"):
            parts = [m.group("dm"), m.group("dmyear")]
        elif m.group("span"):
            which = m.group("which")
            parts = [m.group("spanpart"), m.group("span"), None if (which or "").lower() == "ini" else which]
        else:
            parts = [m.group("bare_year")]
        return m.group(0), " ".join(p.lower() for p in parts if p)
    written = []
    for word in re.findall(r"[\w-]+", re.match(r"[\w\s-]*", rest).group(0))[:3]:
        if word.lower() in story_words.STOPWORDS:
            break
        written.append(word)
    return " ".join(written), " ".join(written).lower()


def _collective(before: str, belah: bool) -> bool:
    """A word ordinal after `before` means "both"/"all N", not a count (`ordinal_claims`)."""
    return belah or before in _NOT_A_NOUN or (bool(_VERB.fullmatch(before)) and before not in _PREFIXED_NOUNS)


def ordinal_claims(text: str) -> List[Tuple[str, Optional[int], str]]:
    """(claim as written, the count it implies, its key) of every ordinal or series claim in `text`
    (SYS-158 #353): a count the writer inferred, which no digit check sees.
    - "gelombang kedua", "untuk ketiga kalinya", "pemilu ke-5": N. A word ordinal claims a count only
      after a noun or before "kali". After a function word ("kedua negara", "dan ketiga tersangka"),
      after a verb ("menahan kedua tersangka") or before "belah" ("kedua belah pihak") it is a
      collective, not a claim;
    - "untuk kesekian kalinya": at least 3;
    - "tiga hari berturut-turut", "dua pekan beruntun", "tiga kali berturut-turut": N;
    - "pertama kali sejak Maret", "terendah sejak awal tahun": None -- a record, which no count proves.
    The key is what a source must state for the claim to be its own: the word before the ordinal
    and N ("kali N" for "kedua kalinya", "ke-N" for a written number), the series' unit and N, or
    the record with its whole time ("terendah sejak awal maret", "tertinggi sejak 9 januari 2026")."""
    out = []
    for m in _ORDINAL.finditer(text):
        n = int(m.group("n")) if m.group("n") else _ORDINAL_WORDS[m.group("ordinal").lower()]
        before = (m.group("before") or "").lower()
        if m.group("times"):
            key = f"kali {n}"
        elif m.group("n"):
            key = f"ke-{n}"
        elif before and not _collective(before, bool(m.group("belah"))):
            key = f"{before} {n}"
        else:
            continue
        start = m.start() if key == f"{before} {n}" else m.start("ordinal")
        out.append((text[start:m.end("times") if m.group("times") else m.end("ordinal")], n, key))
    out += [(m.group(0), 3, "kesekian") for m in _SEKIAN.finditer(text)]
    out += [(m.group(0), _SERIES_COUNT.get(m.group("n").lower()) or int(m.group("n")),
             f"beruntun {m.group('unit').lower()} {_SERIES_COUNT.get(m.group('n').lower()) or int(m.group('n'))}")
            for m in _SERIES.finditer(text)]
    for m in _RECORD.finditer(text):
        written, key = _record_time(text[m.end():])
        if key:
            record = " ".join(m.group("record").lower().replace("kalinya", "kali").split())
            out.append((m.group(0) + written, None, f"{record} sejak {key}"))
    return out


def stated_claims(source: str) -> Set[str]:
    """The claim keys `source` states (`ordinal_claims`), and each record's key without the year of
    its month or day: "terendah sejak Maret 2026" in a source states "terendah sejak Maret" too, never
    "terendah sejak Maret 2025"; a bare year ("sejak 2019") is the whole time and is kept."""
    keys = {key for _, _, key in ordinal_claims(source)}
    return keys | {key.rsplit(" ", 1)[0] for key in keys if re.search(r" sejak \S.* \d{4}$", key)}


_CHANGE_VERBS = (r"bertambah|naik|meningkat|turun|berkurang|menurun|melonjak|anjlok|merosot|menguat|melemah|"
                 r"membengkak|menyusut|tumbuh")
# "Kini jumlah personel yang dimutasi bertambah menjadi 199 orang": a figure told as the new value of an earlier one.
_CHANGE_CLAIM = re.compile(rf"\b(?:{_CHANGE_VERBS})\b(?:\s+\S+){{0,8}}?\s+(?:men)?jadi\s+"
                           r"(?:(?:sekitar|sebesar|sebanyak|hampir|lebih\s+dari|lebih\s+kurang)\s+)?"
                           r"(?:Rp|US\$|\$)?\s?(?P<number>\d+(?:[.,]\d+)*)", re.IGNORECASE)
_TIME_AFTER = (rf"(?:(?:awal|pertengahan|akhir)\s+)?(?:{_MONTH_NAME}|tahun|kuartal|semester|periode|pekan|bulan|"
               rf"hari\s+ini|kini|saat\s+ini|\d{{1,2}}/\d{{1,2}}|\d{{1,2}}\s+(?:{_MONTH_NAME})|\d{{4}})\b")
# What makes a source's figure a total or the result of a change: a change verb; a total word; or a running
# period, "hingga / sampai / per / sepanjang / sejak" + a time. Not a bare "hingga": the 2026-10-11 Polri
# headline "Rombak 199 Personel Polri, Kakorlantas hingga Wakabaintelkam Diganti" is a list, not a total.
_TOTAL_OR_CHANGE = re.compile(rf"\b(?:{_CHANGE_VERBS}|total|totalnya|kumulatif|akumulasi|keseluruhan)\b"
                              rf"|\b(?:hingga|sampai|per|sepanjang|sejak|s\.d\.?|s/d)\s+{_TIME_AFTER}"
                              r"|\bdari\s+(?:Rp|US\$|\$)?\s?\d", re.IGNORECASE)


def _sentences(text: str) -> List[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def unbacked_changes(text: str, source: str) -> List[str]:
    """SYS-161 (#356): the change claims of `text` -- "(bertambah|naik|turun|...) menjadi N" -- whose N
    no source sentence states as a total or a change: every sentence of `source` holding N (by value)
    lacks a change verb, a total word and a running period (`_TOTAL_OR_CHANGE`). "Kini ... bertambah
    menjadi 199 orang" read two separate Polri telegrams (88, then 199) as a running total; the bansos,
    Bulog and PHK figures it was right for are each stated "hingga akhir September", "sampai awal
    Oktober", "sepanjang Januari-September". A claim whose N no source holds at all is left to
    `unsupported_number`."""
    held = [(s, {value for number in _NUMBER.findall(s) for value in values(number)}) for s in _sentences(source)]
    out = []
    for m in (m for sentence in _sentences(text) for m in _CHANGE_CLAIM.finditer(sentence)):
        wanted = values(m.group("number"))
        holding = [s for s, available in held if wanted & available]
        if holding and not any(_TOTAL_OR_CHANGE.search(s) for s in holding):
            out.append(m.group(0))
    return out


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
