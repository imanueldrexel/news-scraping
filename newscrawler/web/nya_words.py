"""Words ending in -nya, for the search page (ADR-021): which point back, and what they are a form of.

"-nya" is the usual Indonesian back-reference and possessive: "pertumbuhannya" (its growth),
"buyback-nya". Two kinds of word merely end in it:
- a word that is not a clitic at all ("hanya", "punya", "tanya");
- an adverb with no referent ("sebenarnya", "nantinya", "sayangnya"). SYS-144 (#327): a list, not a
  se-...-nya pattern, because "sesudahnya", "setelahnya" and "sebaliknya" do point back. The list
  can never be complete (EXPERIMENTS.md 2026-10-19, `scripts/experiments/sys144/mine_nya_adverbs.py`),
  so the follow-up rule does not rest on it alone: a follow-up that names its own subject is its own
  question whatever adverb it holds (`followup.refers_to_thread`).

Kept as references on purpose, because a question uses them to point back: akibatnya, sebaliknya,
karenanya, artinya, hasilnya, intinya, rencananya, alasannya, dampaknya, menurutnya, sesudahnya,
setelahnya, utamanya ("tujuan utamanya"), rasanya ("bagaimana rasanya").
"""
import re
from typing import Optional

from newscrawler.core import story_words

# SYS-146 send-back (#412): every affixed form of "tanya" ("ditanya" was cut to "dita"). Not a suffix
# test: "datanya", "kotanya", "lampunya" are possessives that end in -tanya / -punya.
NOT_CLITIC = frozenset({"hanya", "punya", "tanya", "bertanya", "ditanya", "menanya", "tertanya",
                        "tanya-tanya", "bertanya-tanya",
                        "penanya"})       # QA 2026-10-20 (#423): the questioner, cut to "pena" (pen)

ADVERBS = frozenset({
    # SYS-144 (2026-10-12)
    "sebenarnya", "sesungguhnya", "selanjutnya", "sebelumnya", "biasanya", "akhirnya", "misalnya",
    "khususnya", "terutamanya", "sepertinya", "tampaknya", "nampaknya", "kelihatannya", "rupanya",
    "agaknya", "seharusnya", "semestinya", "setidaknya", "sekurangnya", "umumnya", "tentunya", "katanya",
    # QA's held-out six (2026-10-13)
    "sebaiknya", "sebetulnya", "nantinya", "sayangnya", "secepatnya", "sepenuhnya",
    # sentence adverbs from the corpus (mine_nya_adverbs.py, 20,000 articles), read by hand
    "menariknya", "ironisnya", "pasalnya", "faktanya", "nyatanya", "kenyataannya", "idealnya", "sejatinya",
    "pastinya", "tadinya", "mulanya", "awalnya", "kabarnya", "makanya", "tepatnya", "istilahnya", "jadinya",
    "sedikitnya", "selengkapnya", "untungnya", "kiranya", "sekiranya", "sepatutnya", "selayaknya",
    "seyogianya",
    # SYS-146 send-back (#411): the spoken forms, which are rare enough in the corpus to become a
    # required keyword anchor ("mestinya" -> "mesti", fts=0): a listed se-...-nya adverb without its
    # se- (harusnya, mestinya, baiknya, ...), and QA's aslinya / kayaknya
    "harusnya", "mestinya", "baiknya", "benarnya", "betulnya", "patutnya", "aslinya", "kayaknya",
    "keliatannya",
})

_MIN_ROOT = 3       # "gajinya" -> "gaji"; a shorter remainder is no word of its own


# ADR-022 (SYS-144/145 send-back, #408/#409): a -nya word right after "yang" stands where an adverb does --
# "Apa yang harusnya / aslinya / mestinya terjadi pada Garuda?": the clause's subject is "apa" -- so it points at
# nothing, listed or not. A verb with its object clitic does point back ("Siapa yang memimpinnya?").
_AFTER_YANG = re.compile(r"\byang\s+$", re.IGNORECASE)
# QA 2026-10-20 (#421, #423): so does a -nya word that opens the question before a clause with its own
# interrogative subject -- "Ujung-ujungnya apa yang terjadi pada Sritex?", "Anehnya, apa yang terjadi ...?" --
# "<interrogative> yang" next, a comma or not. "Dampaknya apa?" and "Harganya, berapa?" are no such clause: the
# interrogative is their predicate.
_INTERROGATIVE = r"(?:apa|apakah|siapa|bagaimana|gimana|kapan|berapa|mengapa|kenapa|mana|dimana)"
_CLAUSE_AFTER = re.compile(rf"\s*,?\s+{_INTERROGATIVE}\s+yang\b", re.IGNORECASE)
# QA 2026-11-06 (held out on #421-#423): or, after a comma, before an interrogative whose clause has a subject of its
# own and names what it is about -- "Anehnya, kenapa saham di Garuda Indonesia anjlok?", "Parahnya, bagaimana nasib
# Waskita?". Not "Harganya, berapa sekarang?" (no name) nor "Dampaknya, bagaimana ke IHSG?" (a preposition follows the
# interrogative: the name is what the thread's event affects, ADR-021).
_OWN_CLAUSE_AFTER = re.compile(rf"\s*,\s*({_INTERROGATIVE}\s+([^\W\d_][\w-]*)[^,;:?!.]*)", re.IGNORECASE)
_NOTHING_BEFORE = re.compile(r"^\W*$")


def in_adverb_place(text: str, start: int, word: str) -> bool:
    """The -nya `word` at `start` of `text` stands where an adverb does, whatever word it is: right after "yang"
    and no verb (ADR-022), or opening the question before a clause with its own interrogative subject (#421) or
    with its own subject and name (#421-#423 held out).
    The search page's two halves read it alike: `followup` (no reference) and `keywords` (no keyword)."""
    before = text[:start]
    if _AFTER_YANG.search(before) and not story_words.is_verb(word[:-3]):
        return True
    if not _NOTHING_BEFORE.match(before):
        return False
    if _CLAUSE_AFTER.match(text, start + len(word)):
        return True
    own = _OWN_CLAUSE_AFTER.match(text, start + len(word))
    return bool(own and own.group(2).lower() not in story_words.STOPWORDS and story_words.names(own.group(1)))


def is_reference(word: str) -> bool:
    """A word ending in -nya that points at something: neither an adverb nor a non-clitic."""
    low = (word or "").lower()
    return low.endswith("nya") and low not in ADVERBS and low not in NOT_CLITIC


def possessive_root(word: str) -> Optional[str]:
    """The word a possessive -nya is attached to ("pemimpinnya" -> "pemimpin", "buyback-nya" ->
    "buyback"), lower case; None for any other word, and when the root would be under _MIN_ROOT
    letters (SYS-146 #331: the paragraphs write the root, so the root is what is matched)."""
    if not is_reference(word):
        return None
    root = word.lower()[:-3].rstrip("-")
    return root if len(root) >= _MIN_ROOT else None
