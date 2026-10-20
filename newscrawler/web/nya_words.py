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
from typing import Optional

# SYS-146 send-back (#412): every affixed form of "tanya" ("ditanya" was cut to "dita"). Not a suffix
# test: "datanya", "kotanya", "lampunya" are possessives that end in -tanya / -punya.
NOT_CLITIC = frozenset({"hanya", "punya", "tanya", "bertanya", "ditanya", "menanya", "tertanya",
                        "tanya-tanya", "bertanya-tanya"})

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
