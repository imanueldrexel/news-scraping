"""The words of a story's text that say what it is about, for the newsletter's
word-level checks: the edition's echo guard (SYS-83 #240, SYS-86 #246) and the
summary's subject check (SYS-80 #236).

A *content word* is a word that can tell one story from another. Not one:
- a function word or a day/time word ("yang", "Senin", "pekan");
- a title or office ("Presiden", "Gubernur", "Menteri"): it names a post, not
  who holds it, so "Presiden Prabowo Subianto" made every two Prabowo stories
  share a word (SYS-86);
- a month ("Oktober"): a date, not a subject;
- a number unit ("triliun", "persen", "senilai"): the number itself is no
  content word, so neither is its unit -- "senilai Rp3,5 triliun" and "senilai
  Rp2,4 triliun" are two different amounts;
- a token with a digit ("Rp2", from Rp2.574.000) or a currency prefix ("US"
  in "US$84").

A content word is a *name* when it is an acronym (KPK, BI) or capitalised where
no sentence starts. A sentence-opening word is ambiguous ("Pemerintah ...",
"Komdigi ...") and is not a name; it still counts as a content word.
"""
import re
from typing import Dict, Set

from newscrawler.core import newsletter_copy as copy

STOPWORDS = frozenset(
    "yang dan di ke dari untuk dengan pada ini itu akan dalam oleh atau juga sebagai karena hingga saat usai "
    "setelah tidak tak bisa ada para lebih jadi menjadi bagi serta agar namun telah sudah masih baru kata "
    "sebut menyebut menurut hari tahun bulan pekan senin selasa rabu kamis jumat sabtu minggu "
    "soal tentang terkait terhadap atas bahwa antara sejak per paling "
    "the of and".split())                       # "The Fed": an English article is not a name
TITLES = frozenset(
    "presiden wapres wakil menteri menko wamen gubernur wagub bupati wabup wali walikota ketua kepala direktur "
    "dirut komisaris sekretaris sekjen jenderal juru bicara jubir plt pj "
    "pt tbk persero".split())                   # a legal form names a kind of company, not which one
UNITS = frozenset("ribu juta miliar triliun persen senilai sebesar sekitar".split())
MONTHS = frozenset(m.lower() for m in copy.MONTHS + copy.MONTHS_SHORT)
_NOT_CONTENT = STOPWORDS | TITLES | UNITS | MONTHS

WORD = re.compile(r"[^\W\d_][\w-]*", re.UNICODE)
_ROMAN = re.compile(r"(?=[IVX]{2,}$)X{0,3}(IX|IV|V?I{0,3})$")    # "Komisi VIII", "Paket IV": an ordinal


def _is_content(word: str, text: str, end: int) -> bool:
    low = word.lower()
    if len(word) < 2 or (len(word) < 3 and not word.isupper()) or _ROMAN.match(word):
        return False
    if any(ch.isdigit() for ch in word) or text[end:end + 1] == "$":
        return False
    return not all(part in _NOT_CONTENT for part in low.split("-") if part)   # "Oktober-Desember"


def content_words(text: str) -> Dict[str, bool]:
    """{lower-cased content word: is it a name anywhere in `text`}."""
    out: Dict[str, bool] = {}
    for m in WORD.finditer(text):
        word = m.group(0)
        if not _is_content(word, text, m.end()):
            continue
        before = text[:m.start()].rstrip()
        opens_sentence = not before or before[-1] in ".!?"
        name = (word.isupper() and len(word) >= 2) or (word[0].isupper() and not opens_sentence)
        low = word.lower()
        out[low] = out.get(low, False) or name
    return out


def title_case(text: str) -> bool:
    """True for a Title Case Heading -- every word of four letters or more
    capitalised -- whose capitals say nothing about names. An Indonesian
    sentence-case judul has a lowercase verb ("dikelola", "luncurkan"); the
    model still copies a portal's Title Case headline for ~1 judul in 13
    (replay 2026-10-05: "Netanyahu Pidato di PBB, Puluhan Delegasi Walk Out")."""
    long_words = [w for w in WORD.findall(text) if len(w) >= 4]
    return len(long_words) >= 3 and all(w[0].isupper() for w in long_words)


def story_content_words(judul: str, body: str) -> Dict[str, bool]:
    """content_words of a story's judul and a sentence of it (inti or sekilas),
    the judul's capitals ignored when it is in Title Case."""
    out = content_words(body)
    for word, is_name in content_words(judul).items():
        out[word] = out.get(word, False) or (is_name and not title_case(judul))
    return out


def names(text: str) -> Set[str]:
    """The content words of `text` that are names there, lower-cased, and the
    parts of a hyphenated one ("AS-Iran" gives as-iran, as, iran: an article
    may write "AS dan Iran")."""
    out = {word for word, is_name in content_words(text).items() if is_name}
    return out | {part for word in out if "-" in word for part in word.split("-")
                  if len(part) >= 2 and part not in _NOT_CONTENT}


def vocabulary(text: str) -> Set[str]:
    """Every word of `text`, lower-cased, whatever its case or position, and the
    parts of a hyphenated one ("BI-Rate" gives bi-rate, bi, rate): what a name
    is looked up in."""
    out: Set[str] = set()
    for m in WORD.finditer(text):
        word = m.group(0).lower()
        out.add(word)
        out.update(part for part in word.split("-") if part)
    return out
