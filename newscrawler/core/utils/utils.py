import re
import logging

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def preprocess_text(text):
    text = text.strip()
    text = text.replace("\n", "")
    text = text.replace("\xa0", " ")
    text = re.sub(r" {2,}", " ", text)

    return text


def own_paragraph_text(p_tag, separator: str = " ") -> str:
    """SRC-54 (#177): the text of one <p>, without the text of any <p> nested in it.

    A page that leaves <p> unclosed (EMITENNEWS) is parsed by html.parser as a
    chain -- every following <p> becomes a child of the one before. `get_text()`
    of each element then returns that paragraph plus every paragraph after it,
    and a `find_all("p")` loop stores the article body several times over. The
    paragraph's own inline markup (<strong>, <a>, <em>) is kept; only strings
    that sit inside a nested <p> are skipped."""
    parts = []
    for string in p_tag.strings:
        parent = string.parent
        while parent is not None and parent is not p_tag and parent.name != "p":
            parent = parent.parent
        if parent is p_tag:
            parts.append(string)
    return separator.join(s.strip() for s in parts if s.strip())


# A repeated paragraph shorter than this is a legitimate echo ("(*)", a dateline
# on its own line), not a cascade.
CASCADE_MIN_SUFFIX_CHARS = 20


def cascaded_pairs(paragraphs) -> int:
    """SRC-54: how many consecutive paragraph pairs have the second one as a suffix
    of the first -- the signature of nested-<p> extraction. A clean body has 0."""
    paras = [p.strip() for p in (paragraphs or []) if p and p.strip()]
    return sum(
        1 for prev, cur in zip(paras, paras[1:])
        if len(cur) >= CASCADE_MIN_SUFFIX_CHARS and len(cur) < len(prev) and prev.endswith(cur)
    )


def is_cascaded(paragraphs) -> bool:
    """SRC-54: the QA fleet scan's definition -- at least two cascaded pairs."""
    return cascaded_pairs(paragraphs) >= 2
