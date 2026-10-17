"""SYS-152 (#342, ADR-018): a story arc's causal claim must rest on ONE source sentence.

A sentence that links two facts with a causal word ("karena", "akibat", "sehingga", ...) is kept only when the
model's `sebab` list quotes one source sentence -- or two adjacent ones ("... Hal ini menyebabkan ...") -- that

1. is really in the numbered source the entry names (normalised: case, spacing and punctuation ignored, "..."
   may bridge within that source),
2. itself holds a causal word, and
3. covers BOTH halves of the arc's sentence: the effect clause and the cause clause each share at least
   `MIN_HALF_OVERLAP` of their content words (`story_words`) with that same quote.

Why both halves against one quote: the 10-09 MK arc wrote "MK ... tidak dapat mendiskualifikasinya karena
permohonan tidak dapat diterima". Each half was true and quotable on its own; no source sentence linked them
(the sources: inadmissible for lack of standing; disqualification "bukan ranah MK"). A check per half, per
atomic fact, or per cause clause passes that sentence. Naming who said it exempts nothing either: "MK
menyatakan" made the invented link read as the court's reasoning.

The direction of the connective ("X karena Y" vs "Y sehingga X") does not matter here: both halves are measured
against the same quote. A sentence that opens on its causal word ("Akibatnya, ...", "Karena itu, ...") takes the
previous sentence of the same field as its other half.
"""
import re
from typing import Dict, List, NamedTuple, Sequence, Tuple

from newscrawler.core import story_words

MIN_HALF_OVERLAP = 0.6
MAX_QUOTE_SENTENCES = 2       # one sentence, or two adjacent ("Hal ini menyebabkan ...")
MAX_QUOTE_WORDS = 70          # scraped text glues sentences ("ditebak.Dia ..."): a paragraph is no quote
MIN_HALF_WORDS = 2            # a clause with fewer content words is widened by one clause

CAUSAL = re.compile(r"\b(?:karena(?:nya)?|akibat(?:nya)?|lantaran|dipicu|memicu|sehingga|imbas(?:nya)?|"
                    r"disebabkan|menyebabkan|sebab)\b", re.IGNORECASE)
# Where a clause ends: punctuation (not the decimal comma of "2,85"), or a conjunction that opens a new clause.
# Not "dan"/"serta": they mostly join names ("di Koto Tangah dan Kuranji", replay 10-11), and a clause they open
# follows a comma anyway (", dan Kemnaker menyatakan ..."). A temporal conjunction opens the clause that carries the
# event ("... penantian panjang setelah Perpres Ojol disebut belum terbit karena ..."); "sejak"/"saat" mostly open
# a time phrase ("sejak Sabtu siang") and are not boundaries.
_BOUNDARY = re.compile(r",(?!\d)|[;:()—–]|\s-\s|"
                       r"\b(?:tetapi|namun|sementara|meski(?:pun)?|padahal|setelah|sebelum|ketika|usai)\b", re.IGNORECASE)
# Modal and aspect words carry no fact of their own: "tidak dapat mendiskualifikasinya" must be matched on
# "mendiskualifikasi", not on "dapat", which nearly every legal sentence holds.
_GENERIC = frozenset("dapat harus mampu perlu tengah sedang kini semula sempat kembali".split())
# "yang menurut analis X" names who says it; it is not a fact of either half.
_ATTRIBUTION = re.compile(r"\b(?:yang\s+)?menurut\s+[^,;]*", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_ELLIPSIS = re.compile(r"\.{3}|…")
_PREFIXES = ("meng", "meny", "mem", "men", "me", "di", "ter", "ber", "per", "pe")


def sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENTENCE_END.split(text or "") if s.strip()]


def _norm(text: str) -> str:
    """Lower-cased with every non-word character removed: spacing, quote marks, dashes and "Rp 10" vs "Rp10"
    never decide whether a quote is in the source."""
    return re.sub(r"[\W_]+", "", text.lower())


def _root(word: str) -> str:
    """A rough Indonesian root, enough to meet "ditunda"/"menunda", "mendiskualifikasinya"/"mendiskualifikasi"."""
    w = word.lower()
    if w.endswith("nya") and len(w) > 6:
        w = w[:-3]
    for prefix in _PREFIXES:
        if w.startswith(prefix) and len(w) - len(prefix) >= 4:
            return w[len(prefix):]
    return w


def _roots(text: str) -> set:
    return {_root(w) for w in story_words.content_words(text) if w not in _GENERIC}


def _meets(root: str, others: set) -> bool:
    """`root` is in `others`, or one ends the other (a nasal prefix eats a letter: "unda" in "tunda")."""
    return root in others or any(min(len(root), len(o)) >= 4 and (root.endswith(o) or o.endswith(root))
                                 for o in others)


def overlap(half: str, quote: str) -> float:
    """The share of `half`'s content words that `quote` also holds; 0.0 for a half with none."""
    mine, theirs = _roots(half), _roots(quote)
    return sum(_meets(r, theirs) for r in mine) / len(mine) if mine else 0.0


def quote_in(quote: str, source: str) -> bool:
    """`quote` is in `source` as written, up to case, spacing and punctuation; "..." may skip text between its
    pieces, which must still come in order."""
    pieces = [_norm(p) for p in _ELLIPSIS.split(quote)]
    pieces = [p for p in pieces if p]
    haystack, at = _norm(source), 0
    if not pieces:
        return False
    for piece in pieces:
        found = haystack.find(piece, at)
        if found < 0:
            return False
        at = found + len(piece)
    return True


def _clauses(text: str) -> List[str]:
    return [c for c in _BOUNDARY.split(_ATTRIBUTION.sub(" ", text)) if c and c.strip()]


class Span(NamedTuple):
    """One causal word of an arc sentence, with the half on each side of it. `*_core` is the clause right next to
    the causal word; `before`/`after` widen it while it holds fewer than `MIN_HALF_WORDS` content words."""
    sentence: str
    word: str
    before: str
    after: str
    before_core: str
    after_core: str


def _half(clauses: List[str], from_end: bool) -> Tuple[str, str]:
    """(the clause next to the causal word, that clause widened while it holds fewer than `MIN_HALF_WORDS`
    content words)."""
    ordered = list(reversed(clauses)) if from_end else clauses
    taken: List[str] = []
    for clause in ordered:
        taken.append(clause)
        if len(_roots(" ".join(taken))) >= MIN_HALF_WORDS:
            break
    core = taken[0].strip() if taken else ""
    return core, " ".join(reversed(taken) if from_end else taken).strip()


def causal_spans(text: str) -> List[Span]:
    """Every causal word in `text`, with its sentence and both halves."""
    spans = []
    sents = sentences(text)
    for i, sentence in enumerate(sents):
        for m in CAUSAL.finditer(sentence):
            before_core, before = _half(_clauses(sentence[:m.start()]), from_end=True)
            if not _roots(before) and i > 0:          # "Akibatnya, ...": the cause is the sentence before
                before_core = before = sents[i - 1]
            after_core, after = _half(_clauses(sentence[m.end():]), from_end=False)
            spans.append(Span(sentence, m.group(0), before, after, before_core, after_core))
    return spans


def _covered(core: str, half: str, quote: str) -> bool:
    """The half is covered, and so is the clause next to the causal word on its own: widening must never let the
    context carry a half whose own words are missing ("MK menyatakan ... SMA, tetapi tidak dapat
    mendiskualifikasinya" -- the replay found a source holding the first clause, never "mendiskualifikasi")."""
    return overlap(half, quote) >= MIN_HALF_OVERLAP and (not _roots(core) or overlap(core, quote) >= MIN_HALF_OVERLAP)


def supports(quote: str, span: Span) -> bool:
    """One quote that holds a causal word and covers both halves of the arc's sentence."""
    return (bool(CAUSAL.search(quote)) and _covered(span.before_core, span.before, quote)
            and _covered(span.after_core, span.after, quote))


def quotable(quote: str) -> bool:
    """Short enough to be one quote: at most `MAX_QUOTE_SENTENCES` sentences and `MAX_QUOTE_WORDS` words."""
    return len(sentences(quote)) <= MAX_QUOTE_SENTENCES and len(quote.split()) <= MAX_QUOTE_WORDS


def valid_quotes(entries: Sequence[Tuple[int, str]], sources: Dict[int, str]) -> Tuple[List[str], List[str]]:
    """(the quotes that may back a causal claim, a problem for each that may not)."""
    good, problems = [], []
    for k, (n, quote) in enumerate(entries):
        if n not in sources:
            problems.append(f'sebab [{k}] menunjuk [{n}], yang bukan artikel terkait atau cuplikan alur yang dipilih')
        elif not quotable(quote):
            problems.append(f"sebab [{k}] memuat lebih dari {MAX_QUOTE_SENTENCES} kalimat atau {MAX_QUOTE_WORDS} "
                            "kata: kutip satu kalimat, atau dua kalimat berurutan")
        elif not quote_in(quote, sources[n]):
            problems.append(f'sebab [{k}] tidak tertulis persis di [{n}]: salin kalimatnya kata demi kata')
        elif not CAUSAL.search(quote):
            problems.append(f'sebab [{k}] tidak memuat kata sebab-akibat: kalimat sumber itu tidak menyebut '
                            "hubungan sebab-akibat")
        else:
            good.append(quote)
    return good, problems


def unbacked_causes(fields: Sequence[Tuple[str, str]], entries: Sequence[Tuple[int, str]],
                    sources: Dict[int, str]) -> List[str]:
    """The problems of `fields` [(key, prose)]: each causal claim no single quoted source sentence backs, and
    then why each unusable `sebab` entry is unusable. [] when every causal claim is backed (or there is none)."""
    quotes, entry_problems = valid_quotes(entries, sources)
    problems = []
    for key, value in fields:
        for span in causal_spans(value):
            if not any(supports(q, span) for q in quotes):
                problems.append(f'kalimat "{span.sentence}" di {key} memakai "{span.word}", tetapi tidak ada satu kalimat '
                                "sumber di \"sebab\" yang memuat sebab dan akibatnya sekaligus: hapus kata "
                                "sebab-akibat dan tulis kedua fakta terpisah, atau kutip kalimat sumber itu persis")
    return problems + entry_problems if problems else []
