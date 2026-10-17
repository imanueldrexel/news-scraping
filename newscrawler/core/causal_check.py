"""SYS-152 (#342, ADR-018, ADR-019): a story arc's causal claim must rest on ONE link of ONE quoted source sentence.

A sentence that links two facts with a causal word ("karena", "akibat", "sehingga", ...) is a *claim*: a cause and
an effect. It is kept only when the model's `sebab` list quotes a source sentence -- or two adjacent ones ("... Hal
ini menyebabkan ...") -- that

1. is really in the numbered source the entry names (normalised: case, spacing and punctuation ignored; "..."
   bridges in order), and covers at most `MAX_QUOTE_SENTENCES` sentences and `MAX_QUOTE_WORDS` words OF THE
   SOURCE (SYS-182: counted on the quote as written, "..." or dropped full stops let one "quote" span an article);
2. holds a causal word, whose *link* -- the source's own cause side and effect side around it -- backs the claim:
   the claim's effect shares at least `MIN_HALF_OVERLAP` of its content words (`story_words`) with the link's effect
   side, and the claim's cause with the link's cause side (ADR-019).

Why one link, by direction (QA, 2026-10-17): measured against the whole quote, "Harga avtur melonjak karena harga
tiket naik" was backed by "Harga tiket naik karena harga avtur melonjak" (reversed), and a quote holding two
links lent the effect of one to the cause of the other (SYS-181) -- the 10-09 MK arc's invented link, "MK tidak
dapat mendiskualifikasinya karena permohonan tidak dapat diterima", in a new shape. Naming who said it exempts
nothing: "MK menyatakan" made that link read as the court's reasoning.

Each causal word has a direction (`_KINDS`): *backward* words stand after the effect ("X karena Y"), *forward*
words before it ("Y sehingga X"). Where nothing stands before the word in its sentence:
- a forward word takes the previous sentence as the cause ("Akibatnya, ...", "Hal ini menyebabkan ...");
- "penyebabnya" / "pemicunya" take it as the effect ("Harga naik. Penyebabnya, ...");
- any other backward word fronts the cause, "Karena X, Y": the cause is the clause after it, the effect the rest
  of the sentence (SYS-183);
- "Penyebab X adalah Y" splits at the copula.

A negation must agree (SYS-185): "tidak naik karena" is not backed by "naik karena", nor "bukan karena" by
"karena". "berdampak", "terdampak", "terimbas" and "terpicu" are no causal words here: in the corpus they mean
"affected" ("498 jiwa terdampak"), not a link between two stated facts (SYS-184).
"""
import re
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

from newscrawler.core import story_words

MIN_HALF_OVERLAP = 0.6
MAX_QUOTE_SENTENCES = 2       # one sentence, or two adjacent ("Hal ini menyebabkan ...")
MAX_QUOTE_WORDS = 70          # scraped text glues sentences ("ditebak.Dia ..."): a paragraph is no quote
MIN_HALF_WORDS = 2            # a clause with fewer content words is widened by one clause

BACKWARD, FORWARD = "backward", "forward"        # EFFECT <word> CAUSE / CAUSE <word> EFFECT
# SYS-184 (#384): ADR-018's equivalence classes, affixed forms and synonyms included. The prompt lists the same.
_KINDS = {
    "karena": BACKWARD, "dikarenakan": BACKWARD, "lantaran": BACKWARD, "sebab": BACKWARD, "gara-gara": BACKWARD,
    "akibat": BACKWARD, "diakibatkan": BACKWARD, "dipicu": BACKWARD, "disebabkan": BACKWARD, "imbas": BACKWARD,
    "penyebabnya": BACKWARD, "pemicunya": BACKWARD,
    "sehingga": FORWARD, "akibatnya": FORWARD, "karenanya": FORWARD, "imbasnya": FORWARD, "mengakibatkan": FORWARD,
    "berakibat": FORWARD, "menyebabkan": FORWARD, "memicu": FORWARD, "berimbas": FORWARD, "penyebab": FORWARD,
    "pemicu": FORWARD,
}
CAUSAL_WORDS = tuple(_KINDS)
CAUSAL = re.compile(r"\b(?:" + "|".join(sorted(map(re.escape, _KINDS), key=len, reverse=True)) + r")\b",
                    re.IGNORECASE)
_REFERS_BACK = frozenset({"penyebabnya", "pemicunya"})     # "Harga naik. Penyebabnya, ...": the effect is before
_NOUNS = frozenset({"penyebab", "pemicu"})                 # "Penyebab banjir adalah hujan deras"
_THEREFORE = re.compile(r"\s*itu\b", re.IGNORECASE)        # "karena itu", "oleh sebab itu": forward
_COPULA = re.compile(r"\b(?:adalah|ialah|yakni|yaitu|merupakan)\b", re.IGNORECASE)
# Where a clause ends: punctuation (not the decimal comma of "2,85"), or a conjunction that opens a new clause.
# Not "dan"/"serta": they mostly join names ("di Koto Tangah dan Kuranji", replay 10-11), and a clause they open
# follows a comma anyway (", dan Kemnaker menyatakan ..."). A temporal conjunction opens the clause that carries the
# event ("... penantian panjang setelah Perpres Ojol disebut belum terbit karena ..."); "sejak"/"saat" mostly open
# a time phrase ("sejak Sabtu siang") and are not boundaries.
_CONJUNCTION = r"\b(?:tetapi|namun|sementara|sedangkan|meski(?:pun)?|padahal|setelah|sebelum|ketika|usai)\b"
_BOUNDARY = re.compile(r",(?!\d)|[;:()—–]|\s-\s|" + _CONJUNCTION, re.IGNORECASE)
# A source's side ends only where another clause begins: never at a comma, because a source's cause is often a list
# ("disebabkan oleh tingginya dinamika ekonomi global, konflik geopolitik, serta fluktuasi harga komoditas").
_SIDE_END = re.compile(r";|" + _CONJUNCTION, re.IGNORECASE)
# A side that points back ("Peningkatan proyeksi defisit tersebut disebabkan ...") takes the previous sentence too.
_ANAPHOR = re.compile(r"\btersebut\b|\bhal\s+(?:ini|itu)\b", re.IGNORECASE)
# A side that is only a reference: "Hal ini", "Kondisi tersebut", "Itu".
_REFERENCE = re.compile(r"^\W*(?:[^\W\d_]+\s+)?(?:ini|itu|tersebut)\W*$", re.IGNORECASE)
# Modal, aspect and frame words carry no fact of their own: "tidak dapat mendiskualifikasinya" must be matched on
# "mendiskualifikasi", not on "dapat", which nearly every legal sentence holds; "Sebelumnya, karena ..." opens on
# its cause.
_GENERIC = frozenset("dapat harus mampu perlu tengah sedang kini semula sempat kembali sebelumnya kemudian lalu "
                     "selanjutnya selain disebut".split())
_NEGATORS = frozenset({"tidak", "tak", "bukan", "belum"})        # checked by negation_agrees, never as a fact
# Skipped between a negator and the word it negates: "tak kunjung terbit", "tidak hanya", "belum juga".
_NEGATION_SKIP = _GENERIC | frozenset("kunjung pernah lagi juga pula akan bisa boleh hanya semata terlalu".split())
_NEGATED_LINK = re.compile(r"\b(?:tidak|tak|bukan|belum)\s*$", re.IGNORECASE)     # "bukan karena"
# "yang menurut analis X" names who says it; it is not a fact of either half.
_ATTRIBUTION = re.compile(r"\b(?:yang\s+)?menurut\s+[^,;]*", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+|(?<=[a-z][.!?])(?=[A-Z][a-z])")
_ELLIPSIS = re.compile(r"\.{3}|…")
_WORD = re.compile(r"[^\W\d_][\w-]*")
_PREFIXES = ("meng", "meny", "mem", "men", "me", "di", "ter", "ber", "per", "pe")


def _sentence_spans(text: str) -> List[Tuple[int, int]]:
    """(start, end) of each sentence of `text`, stripped of the spaces around it."""
    spans, start = [], 0
    for m in [*_SENTENCE_END.finditer(text), None]:
        end = m.start() if m else len(text)
        piece = text[start:end]
        if piece.strip():
            lead = len(piece) - len(piece.lstrip())
            spans.append((start + lead, start + len(piece.rstrip())))
        if m:
            start = m.end()
    return spans


def sentences(text: str) -> List[str]:
    return [(text or "")[a:b] for a, b in _sentence_spans(text or "")]


def _normalised(text: str) -> Tuple[str, List[int]]:
    """`text` lower-cased with every non-word character removed, and where each kept character stands in `text`:
    spacing, quote marks, dashes and "Rp 10" vs "Rp10" never decide whether a quote is in the source."""
    chars, where = [], []
    for i, ch in enumerate(text):
        for c in ch.lower():
            if c.isalnum():
                chars.append(c)
                where.append(i)
    return "".join(chars), where


def _norm(text: str) -> str:
    return _normalised(text)[0]


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
    return {_root(w) for w in story_words.content_words(text) if w not in _GENERIC and w not in _NEGATORS}


def _meets(root: str, others: set) -> bool:
    """`root` is in `others`, or one ends the other (a nasal prefix eats a letter: "unda" in "tunda")."""
    return root in others or any(min(len(root), len(o)) >= 4 and (root.endswith(o) or o.endswith(root))
                                 for o in others)


def overlap(half: str, side: str) -> float:
    """The share of `half`'s content words that `side` also holds; 0.0 for a half with none."""
    mine, theirs = _roots(half), _roots(side)
    return sum(_meets(r, theirs) for r in mine) / len(mine) if mine else 0.0


def _negated(text: str) -> set:
    """The roots `text` negates: the first word after each negator that is not a modal or function word."""
    words, out = _WORD.findall(text.lower()), set()
    for k, word in enumerate(words):
        if word in _NEGATORS:
            target = next((w for w in words[k + 1:k + 4] if w not in _NEGATION_SKIP
                           and w not in story_words.STOPWORDS), None)
            if target:
                out.add(_root(target))
    return out


def negation_agrees(half: str, side: str) -> bool:
    """SYS-185 (#385): every word `half` negates is negated in `side`, and every negated word of `side` that
    `half` uses is negated in `half` too: "tidak naik" is not "naik", and "naik" is not "tidak naik"."""
    mine, theirs = _negated(half), _negated(side)
    used = _roots(half)
    return (all(_meets(r, theirs) for r in mine)
            and all(_meets(r, mine) for r in theirs if _meets(r, used)))


def locate(quote: str, source: str) -> Optional[Tuple[int, int]]:
    """(start, end) of the text of `source` that `quote` covers, from its first piece to its last; None when
    `quote` is not in `source` as written, up to case, spacing and punctuation. "..." may skip text between its
    pieces, which must still come in order."""
    pieces = [p for p in (_norm(p) for p in _ELLIPSIS.split(quote)) if p]
    haystack, where = _normalised(source)
    if not pieces:
        return None
    at, first = 0, None
    for piece in pieces:
        found = haystack.find(piece, at)
        if found < 0:
            return None
        first = found if first is None else first
        at = found + len(piece)
    return where[first], where[at - 1] + 1


def quote_in(quote: str, source: str) -> bool:
    return locate(quote, source) is not None


def _clauses(text: str) -> List[str]:
    return [c for c in _BOUNDARY.split(_ATTRIBUTION.sub(" ", text)) if c and c.strip()]


def _half(clauses: List[str], from_end: bool) -> Tuple[str, str, int]:
    """(the clause next to the causal word, that clause widened while it holds fewer than `MIN_HALF_WORDS`
    content words, how many clauses that took)."""
    ordered = list(reversed(clauses)) if from_end else clauses
    taken: List[str] = []
    for clause in ordered:
        taken.append(clause)
        if len(_roots(" ".join(taken))) >= MIN_HALF_WORDS:
            break
    core = taken[0].strip() if taken else ""
    return core, " ".join(reversed(taken) if from_end else taken).strip(), len(taken)


class Span(NamedTuple):
    """One causal word with the cause and the effect it links. `*_core` is the clause right next to the causal word
    (the whole side, in a source). `cause_first` is the reading order; `negated` is a denied link ("bukan karena")."""
    sentence: str
    word: str
    cause: str
    effect: str
    cause_core: str
    effect_core: str
    cause_first: bool
    negated: bool

    @property
    def before(self) -> str:
        return self.cause if self.cause_first else self.effect

    @property
    def after(self) -> str:
        return self.effect if self.cause_first else self.cause

    @property
    def before_core(self) -> str:
        return self.cause_core if self.cause_first else self.effect_core

    @property
    def after_core(self) -> str:
        return self.effect_core if self.cause_first else self.cause_core


def _prose_side(text: str, from_end: bool) -> Tuple[str, str]:
    core, widened, _ = _half(_clauses(text), from_end)
    return core, widened


def _source_side(text: str, from_end: bool) -> Tuple[str, str]:
    side = _SIDE_END.split(_ATTRIBUTION.sub(" ", text))[-1 if from_end else 0].strip()
    return side, side


def _fronted(text: str, side) -> Tuple[str, str, str, str]:
    """SYS-183 (#383): (cause, effect, cause core, effect core) of "Karena X, Y" from the text after the causal
    word. The cause runs to the first clause boundary after which it holds `MIN_HALF_WORDS` content words; with
    no such boundary the effect cannot be told apart and is empty (the claim fails closed)."""
    cut = next((b for b in _BOUNDARY.finditer(text) if len(_roots(text[:b.start()])) >= MIN_HALF_WORDS), None)
    if cut is None:
        return text.strip(), "", text.strip(), ""
    cause = text[:cut.start()].strip()
    effect_core, effect = side(text[cut.end():], False)
    return cause, effect, cause, effect_core


def _groups(sentence: str) -> List[Tuple[int, int]]:
    """(start, end) of each run of causal words with nothing but spaces between them: "karena dipicu" is one link."""
    runs: List[List[int]] = []
    for m in CAUSAL.finditer(sentence):
        if runs and not sentence[runs[-1][1]:m.start()].strip():
            runs[-1][1] = m.end()
        else:
            runs.append([m.start(), m.end()])
    return [(a, b) for a, b in runs]


def _cut(sents: List[str], i: int, m, source: bool) -> Span:
    """The claim (prose) or the link (`source`) of causal word `m` in sentence `i` of `sents`. Each side stops at
    the next causal word of the sentence: "A memicu B, sehingga C" is two links, B's cause is A, C's is B."""
    sentence, word = sents[i], m.group(0)
    kind = _KINDS[word.lower()]
    runs = _groups(sentence)
    start, end = next((a, b) for a, b in runs if a <= m.start() < b)
    left = max([b for a, b in runs if b <= start], default=0)
    right = min([a for a, b in runs if a >= end], default=len(sentence))
    before_text, after_text = sentence[left:start], sentence[end:right]
    side = _source_side if source else _prose_side
    if kind == BACKWARD and _THEREFORE.match(after_text):                          # "karena itu, ..."
        kind = FORWARD
    negated = bool(_NEGATED_LINK.search(before_text))
    before_core, before = side(before_text, True)
    if not _roots(before) and word.lower() in _NOUNS:                              # "Penyebab X adalah Y"
        copula = _COPULA.search(after_text)
        effect = after_text[:copula.start()].strip() if copula else ""
        cause = after_text[copula.end():].strip() if copula else ""
        return Span(sentence, word, cause, effect, cause, effect, False, negated)
    if kind == BACKWARD and not _roots(before) and word.lower() not in _REFERS_BACK:
        return Span(sentence, word, *_fronted(after_text, side), True, negated)
    after_core, after = side(after_text, False)
    # A side that only points back ("Akibatnya,", "Hal ini menyebabkan") is the sentence before it. A source side
    # that names its subject by an anaphor ("Peningkatan proyeksi defisit tersebut disebabkan") takes that sentence
    # too: ADR-018's two-sentence allowance, and the only way a quote's second sentence lends a half.
    previous = sents[i - 1] if i > 0 else ""
    if previous and (not _roots(before) or _REFERENCE.match(before)):
        before_core = before = previous + (f" {before}" if source else "")
    elif previous and source and (len(_roots(before)) < MIN_HALF_WORDS or _ANAPHOR.search(before)):
        before_core = before = f"{previous} {before}"
    if kind == FORWARD:
        return Span(sentence, word, before, after, before_core, after_core, True, negated)
    return Span(sentence, word, after, before, after_core, before_core, False, negated)


def causal_spans(text: str) -> List[Span]:
    """Every causal claim in `text`: each causal word, with its sentence, cause and effect."""
    sents = sentences(text)
    return [_cut(sents, i, m, source=False) for i, sentence in enumerate(sents) for m in CAUSAL.finditer(sentence)]


def _covers(half: str, side: str, sentence: str) -> bool:
    """At least `MIN_HALF_OVERLAP` of `half`'s event words are on `side`, and of all its content words when a name (a
    place, a person) may stand anywhere in the link's `sentence`. A name locates the event; the event words carry
    the link. Replay 10-11 (v4): "hujan deras memicu luapan air sungai di Koto Tangah" -- the source names Koto
    Tangah after its next causal word ("... memicu luapan debit air sungai hingga menyebabkan tanggul jebol di ...
    Koto Tangah"). A half of names only gets no such room."""
    words = story_words.content_words(half)
    events = {_root(w) for w, is_name in words.items() if not is_name and w not in _GENERIC | _NEGATORS}
    if not events:
        return overlap(half, side) >= MIN_HALF_OVERLAP
    names = {_root(w) for w, is_name in words.items() if is_name} - events
    on_side, in_sentence = _roots(side), _roots(side) | _roots(sentence)
    found = sum(_meets(r, on_side) for r in events)
    return (found / len(events) >= MIN_HALF_OVERLAP
            and (found + sum(_meets(r, in_sentence) for r in names)) / (len(events) + len(names)) >= MIN_HALF_OVERLAP)


def _covered(core: str, half: str, side: str, sentence: str) -> bool:
    """The half is covered, and so is the clause next to the causal word on its own: widening must never let the
    context carry a half whose own words are missing ("MK menyatakan ... SMA, tetapi tidak dapat
    mendiskualifikasinya" -- the replay found a source holding the first clause, never "mendiskualifikasi")."""
    return _covers(half, side, sentence) and (not _roots(core) or _covers(core, side, sentence))


def supports(link: Span, claim: Span) -> bool:
    """`link` (a causal word of a quoted source) backs `claim`: effect to effect side, cause to cause side, the
    negations agreeing (ADR-019)."""
    return (link.negated == claim.negated
            and _covered(claim.effect_core, claim.effect, link.effect, link.sentence)
            and negation_agrees(claim.effect, link.effect)
            and _covered(claim.cause_core, claim.cause, link.cause, link.sentence)
            and negation_agrees(claim.cause, link.cause))


def quotable(quote: str) -> bool:
    """Short enough to be one quote as written: at most `MAX_QUOTE_SENTENCES` sentences and `MAX_QUOTE_WORDS`
    words. What it covers in the source is counted again (`links`)."""
    return len(sentences(quote)) <= MAX_QUOTE_SENTENCES and len(quote.split()) <= MAX_QUOTE_WORDS


def links(quote: str, source: str) -> Tuple[List[Span], str]:
    """(the links of `source` that `quote` points at, "") -- every causal word inside the quoted text, cut from the
    whole source sentences it covers -- or ([], what is wrong with the quote)."""
    where = locate(quote, source)
    if where is None:
        return [], "absent"
    first, last = where
    spans = [(a, b) for a, b in _sentence_spans(source) if b > first and a < last]
    if len(spans) > MAX_QUOTE_SENTENCES or sum(len(source[a:b].split()) for a, b in spans) > MAX_QUOTE_WORDS:
        return [], "long"
    sents = [source[a:b] for a, b in spans]
    found = [_cut(sents, j, m, source=True) for j, s in enumerate(sents) for m in CAUSAL.finditer(s)
             if first <= spans[j][0] + m.start() < last]
    return found, "" if found else "no causal word"


def backs(quote: str, source: str, claim: Span) -> bool:
    """`quote`, a valid quote of `source`, points at a link that backs `claim`."""
    return quotable(quote) and any(supports(link, claim) for link in links(quote, source)[0])


def match_counts(entries: Sequence[Tuple[int, str]], sources: Dict[int, str]) -> Dict[str, int]:
    """SYS-152's measurement: how many quotes stand in their source verbatim, only after normalisation, or not at
    all (a quote naming no quotable source counts as absent)."""
    counts = {"verbatim": 0, "normalised": 0, "absent": 0}
    for n, quote in entries:
        source = sources.get(n, "")
        verbatim = all(piece.strip() in source for piece in _ELLIPSIS.split(quote) if piece.strip())
        key = "verbatim" if verbatim and quote.strip() else "normalised" if quote_in(quote, source) else "absent"
        counts[key] += 1
    return counts


def valid_quotes(entries: Sequence[Tuple[int, str]], sources: Dict[int, str]) -> Tuple[List[Span], List[str]]:
    """(the links the quotes point at, a problem for each quote that points at none)."""
    good: List[Span] = []
    problems = []
    for k, (n, quote) in enumerate(entries):
        if n not in sources:
            problems.append(f'sebab [{k}] menunjuk [{n}], yang bukan artikel terkait atau cuplikan alur yang dipilih')
            continue
        found, wrong = links(quote, sources[n]) if quotable(quote) else ([], "long")
        if wrong == "long":
            problems.append(f"sebab [{k}] memuat lebih dari {MAX_QUOTE_SENTENCES} kalimat atau {MAX_QUOTE_WORDS} "
                            f"kata di [{n}]: kutip satu kalimat, atau dua kalimat berurutan")
        elif wrong == "absent":
            problems.append(f'sebab [{k}] tidak tertulis persis di [{n}]: salin kalimatnya kata demi kata')
        elif wrong:
            problems.append(f'sebab [{k}] tidak memuat kata sebab-akibat: kalimat sumber itu tidak menyebut '
                            "hubungan sebab-akibat")
        else:
            good += found
    return good, problems


def unbacked_causes(fields: Sequence[Tuple[str, str]], entries: Sequence[Tuple[int, str]],
                    sources: Dict[int, str]) -> List[str]:
    """The problems of `fields` [(key, prose)]: each causal claim no single link of a quoted source sentence backs,
    and then why each unusable `sebab` entry is unusable. [] when every causal claim is backed (or there is none)."""
    found, entry_problems = valid_quotes(entries, sources)
    problems = []
    for key, value in fields:
        for claim in causal_spans(value):
            if not any(supports(link, claim) for link in found):
                problems.append(f'kalimat "{claim.sentence}" di {key} memakai "{claim.word}", tetapi tidak ada satu '
                                "kalimat sumber di \"sebab\" yang memuat sebab dan akibatnya sekaligus, dengan arah "
                                "yang sama: hapus kata sebab-akibat dan tulis kedua fakta terpisah, atau kutip "
                                "kalimat sumber itu persis")
    return problems + entry_problems if problems else []
