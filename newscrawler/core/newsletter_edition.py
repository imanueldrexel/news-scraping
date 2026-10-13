"""The 5-minute edition (SYS-83 #240): the day's 6-8 top stories, a 60-second
block and a one-line Sekilas list, in at most WORD_BUDGET words.

It is built from the full digest's shown clusters after SYS-82 summarized them --
no extra summary calls. One editor call reads the candidates' `inti` (not only
their headlines, so it sees two clusters that report the same event) and answers
JSON: which candidates are duplicates, which are `utama`, and the 60-second
sentences. `parse_editor` holds the answer to the owner's rules (2026-10-05):
6-8 stories, at most 2 per section, at least 2 non-finance when non-finance
stories carried by >= 3 portals exist, one story per event, 3-5 sentences of
<= 18 words about different top stories with no number the articles lack. A
refused answer is asked again once with the reason; then `deterministic` picks
by portal count under the same quotas, finance first, and the 60-second block is
the top four stories' `sekilas` lines. The fallback is counted, like SYS-68's.

The full digest is unchanged by this module: it stays the archive, the edition
is a second file, digests/YYYY-MM-DD-ringkas.md, in the same markdown grammar
(newsletter_pdf renders it for a phone, OPS-42).
"""
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

from newscrawler.core import newsletter_copy as copy
from newscrawler.core import story_words
from newscrawler.core.filter_rubric import TOPICS_FINANCE
from newscrawler.core.source_check import unsupported_number
from newscrawler.core.story_summary import RETRY, Rejected, words
from newscrawler.core.summarizer import QuotaExhausted, SummarizerError

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

CANDIDATES_PER_SECTION = 3
UTAMA_MIN, UTAMA_MAX = 6, 8
MAX_PER_SECTION = 2
MIN_NON_FINANCE = 2
NON_FINANCE_MIN_PORTALS = 3
SIXTY_MIN, SIXTY_MAX, SIXTY_WORDS = 3, 5, 18
FALLBACK_UTAMA = 6
FALLBACK_SIXTY = 4
SEKILAS_PER_SECTION = 3
WORD_BUDGET = 1200
EDITION_SUFFIX = "-ringkas"
# CTO/owner decision 2026-10-05 (.10x/decisions/cto/newsletter-5min-edition.md):
# the day's GUARANTEED_TOP largest stories (by portal count) are always candidates and,
# when not a top story, always get a Sekilas line; and a Sekilas line that repeats a top
# story is hidden (`echoes`).
GUARANTEED_TOP = 6
ECHO_MIN_EVENT_WORDS = 2       # shared content words that are not names: what happened, not only who
ECHO_MIN_EVENT_WORDS_UNNAMED = 4   # ... when no name is shared: a name that opens both sentences is not
                                   # recognised ("Komdigi ..."; 10-03's sisa-kuota story twice, v5 replay)

PROMPT = (
    "Kamu pemimpin redaksi briefing berita harian berbahasa Indonesia untuk pembaca yang mengikuti ekonomi\n"
    "dan bisnis. Seluruh edisi harus terbaca dalam 5 menit.\n"
    "\n"
    "Di bawah ada {n} kandidat berita {tanggal}, satu per baris:\n"
    "id | rubrik | jumlah portal | judul | inti\n"
    "\n"
    "TUGAS\n"
    "1. duplikat: kelompokkan id yang membahas peristiwa YANG SAMA (mis. dua berita tentang data IPO BEI yang\n"
    "   sama), bukan sekadar topik yang mirip.\n"
    "2. utama: pilih 6-8 id terpenting, urut dari yang terpenting. Utamakan keputusan resmi, dampak luas bagi\n"
    "   ekonomi, pasar, atau publik, dan jumlah portal yang tinggi. Maks 2 dari rubrik yang sama.\n"
    "   Satu id per peristiwa. Utamakan rubrik ekonomi, tetapi sertakan paling sedikit 2 berita dari rubrik\n"
    "   non-ekonomi bila ada yang penting.\n"
    "3. ringkas_60_detik: 3-5 kalimat SAJA (bukan satu kalimat untuk setiap berita utama), masing-masing\n"
    "   maks 18 kata, tiap kalimat tentang satu berita utama yang berbeda dan terpenting, ditulis ulang dari\n"
    "   \"inti\" tanpa fakta baru.\n"
    "\n"
    "Balas HANYA dengan JSON valid:\n"
    "{{\"duplikat\": [[3, 7]], \"utama\": [12, 3, 5, 18, 1, 9],\n"
    "  \"ringkas_60_detik\": [{{\"id\": 12, \"kalimat\": \"...\"}}]}}\n"
    "\n"
    "KANDIDAT\n"
    "{kandidat}"
)


@dataclass
class Candidate:
    """A shown cluster of the full digest, as the editor sees it. `id` is its
    1-based position: sections in SECTION_ORDER, clusters in rank order.
    `guaranteed`: one of the day's GUARANTEED_TOP largest stories."""
    id: int
    topic: str
    cluster: dict
    guaranteed: bool = False

    @property
    def story(self):
        return self.cluster.get("story")

    @property
    def summarized(self) -> bool:
        return self.story is not None

    @property
    def portals(self) -> int:
        return len(self.cluster["sources"])

    @property
    def finance(self) -> bool:
        return self.topic in TOPICS_FINANCE


@dataclass
class Choice:
    """The edition's picks: `utama` ids most important first, the 60-second
    sentences as (id, sentence), and the duplicate groups (sets of ids)."""
    utama: List[int]
    sixty: List[Tuple[int, str]]
    groups: List[set] = field(default_factory=list)
    sixty_trimmed: int = 0        # 60-second sentences past SIXTY_MAX that were left out (whole)


@dataclass
class Edition:
    markdown: str
    words: int
    utama: int
    sekilas: int
    unsummarized: int             # candidates left out because they have no summary
    editor_fallback: bool
    editor_rejections: List[str]  # each refused or failed editor answer's reason, in order
    sixty_trimmed: int = 0
    echoes_hidden: List[str] = field(default_factory=list)   # Sekilas lines hidden as repeats of a top story

    def stats(self) -> dict:
        """The `_edition` entry of newsletter_digests.categories."""
        return {"built": True, "words": self.words, "utama": self.utama, "sekilas": self.sekilas,
                "unsummarized": self.unsummarized, "editor_fallback": self.editor_fallback,
                "editor_rejections": list(self.editor_rejections), "sixty_trimmed": self.sixty_trimmed,
                "echoes_hidden": list(self.echoes_hidden)}


def edition_path(digest_path: str) -> str:
    """digests/2026-10-04.md -> digests/2026-10-04-ringkas.md"""
    root, ext = os.path.splitext(digest_path)
    return f"{root}{EDITION_SUFFIX}{ext or '.md'}"


def candidates(sections: Sequence[dict]) -> List[Candidate]:
    """Each section's top CANDIDATES_PER_SECTION shown clusters, plus any of the
    day's GUARANTEED_TOP largest (by portal count; ties in section and rank
    order) that rank lower in a crowded section -- 2026-09-28's IHSG close, 14
    portals, was 4th in Pasar behind three 18-19-portal stories."""
    shown = [c for section in sections for c in section["clusters"]]
    top = {id(c) for c in sorted(shown, key=lambda c: -len(c["sources"]))[:GUARANTEED_TOP]}
    out = []
    for section in sections:
        for rank, cluster in enumerate(section["clusters"]):
            if rank < CANDIDATES_PER_SECTION or id(cluster) in top:
                out.append(Candidate(len(out) + 1, section["topic"], cluster, guaranteed=id(cluster) in top))
    return out


def build_prompt(cands: Sequence[Candidate], digest_date: date) -> str:
    lines = [f"{c.id} | {copy.SECTION_NAMES.get(c.topic, c.topic)} | {c.portals} | {c.story.judul} | {c.story.inti}"
             for c in cands if c.summarized]
    return PROMPT.format(n=len(lines), tanggal=copy.tanggal(digest_date), kandidat="\n".join(lines))


# ── Rules ───────────────────────────────────────────────────────────────────

def _merge(groups: Sequence[Sequence[int]]) -> List[set]:
    """Duplicate groups with any shared id joined (the same event is one event)."""
    merged: List[set] = []
    for group in groups:
        group = set(group)
        for other in [m for m in merged if m & group]:
            group |= other
            merged.remove(other)
        if len(group) > 1:
            merged.append(group)
    return merged


def _group_of(cid: int, groups: Sequence[set]):
    for k, group in enumerate(groups):
        if cid in group:
            return k
    return ("own", cid)


def _pick(pool: Sequence[Candidate], limit: int, reserve_non_finance: int, groups: Sequence[set]) -> List[Candidate]:
    """In `pool` order: at most MAX_PER_SECTION per section and one per event;
    the best `reserve_non_finance` non-finance stories first, then finance
    stories, then the remaining non-finance ones, up to `limit`."""
    picked: List[Candidate] = []

    def fits(c):
        return (c not in picked and len(picked) < limit
                and sum(p.topic == c.topic for p in picked) < MAX_PER_SECTION
                and all(_group_of(p.id, groups) != _group_of(c.id, groups) for p in picked))

    for c in pool:
        if not c.finance and sum(not p.finance for p in picked) < reserve_non_finance and fits(c):
            picked.append(c)
    for wanted in (True, False):
        for c in pool:
            if c.finance == wanted and fits(c):
                picked.append(c)
    return picked


def required_non_finance(cands: Sequence[Candidate], groups: Sequence[set] = ()) -> int:
    """How many non-finance top stories the rules ask for: MIN_NON_FINANCE, or
    fewer when fewer distinct non-finance events reached NON_FINANCE_MIN_PORTALS."""
    eligible = {_group_of(c.id, groups) for c in cands
                if c.summarized and not c.finance and c.portals >= NON_FINANCE_MIN_PORTALS}
    return min(MIN_NON_FINANCE, len(eligible))


def _by_portals(cands: Sequence[Candidate]) -> List[Candidate]:
    return sorted((c for c in cands if c.summarized), key=lambda c: (-c.portals, c.id))


def deterministic(cands: Sequence[Candidate], groups: Sequence[set] = ()) -> Choice:
    """The editor's fallback: by portal count under the same quotas, finance first;
    the 60-second block is the top FALLBACK_SIXTY stories' `sekilas` lines."""
    pool = _by_portals(cands)
    picked = _pick(pool, FALLBACK_UTAMA, required_non_finance(cands, groups), groups)
    picked.sort(key=pool.index)
    return Choice([c.id for c in picked], [(c.id, c.story.sekilas) for c in picked[:FALLBACK_SIXTY]], list(groups))


def _ids(value, known: set, what: str) -> List[int]:
    if not isinstance(value, list) or any(not isinstance(i, int) or isinstance(i, bool) for i in value):
        raise Rejected("json", f'"{what}" harus daftar id')
    unknown = [i for i in value if i not in known]
    if unknown:
        raise Rejected("json", f'"{what}" memuat id yang tidak ada di daftar kandidat: {unknown[:3]}')
    return value


def parse_editor(answer: Optional[str], cands: Sequence[Candidate]) -> Choice:
    """The editor's answer as a Choice, or Rejected (reason json, rules, length or number)."""
    match = re.search(r"\{.*\}", answer or "", re.DOTALL)
    try:
        data = json.loads(match.group(0)) if match else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise Rejected("json", "jawaban bukan objek JSON")
    by_id: Dict[int, Candidate] = {c.id: c for c in cands if c.summarized}
    known = set(by_id)

    raw_groups = data.get("duplikat") or []
    if not isinstance(raw_groups, list):
        raise Rejected("json", '"duplikat" harus daftar kelompok id')
    groups = _merge([_ids(g, known, "duplikat") for g in raw_groups])
    utama = _ids(data.get("utama"), known, "utama")
    sixty_raw = data.get("ringkas_60_detik")
    if not isinstance(sixty_raw, list) or any(
            not isinstance(s, dict) or not isinstance(s.get("kalimat"), str) or not s["kalimat"].strip()
            for s in sixty_raw):
        raise Rejected("json", '"ringkas_60_detik" harus daftar {"id": ..., "kalimat": "..."}')
    sixty = [(s.get("id"), " ".join(s["kalimat"].split())) for s in sixty_raw]
    _ids([i for i, _ in sixty], known, "ringkas_60_detik")
    # The replays (2026-10-05) answered one sentence per top story, 8 of them, in 6 of 6 first answers,
    # even with the prompt saying "3-5 kalimat SAJA". The first SIXTY_MAX are kept whole (the model
    # orders them like `utama`, most important first); nothing is cut, and the count is reported.
    trimmed = max(0, len(sixty) - SIXTY_MAX)
    if trimmed:
        logger.info(f"Editor wrote {len(sixty)} 60-second sentences; keeping the first {SIXTY_MAX}.")
        sixty = sixty[:SIXTY_MAX]

    if len(set(utama)) != len(utama):
        raise Rejected("rules", "utama memuat id yang sama dua kali")
    capacity = len(_pick(_by_portals(cands), UTAMA_MAX, 0, groups))
    low = min(UTAMA_MIN, capacity)
    if not low <= len(utama) <= UTAMA_MAX:
        raise Rejected("rules", f"utama berisi {len(utama)} id, harus {low}-{UTAMA_MAX}")
    for topic in {by_id[i].topic for i in utama}:
        if sum(by_id[i].topic == topic for i in utama) > MAX_PER_SECTION:
            raise Rejected("rules", f"lebih dari {MAX_PER_SECTION} berita utama dari rubrik "
                                    f"{copy.SECTION_NAMES.get(topic, topic)}")
    if len({_group_of(i, groups) for i in utama}) != len(utama):
        raise Rejected("rules", "dua berita utama membahas peristiwa yang sama (lihat duplikat)")
    needed = required_non_finance(cands, groups)
    if sum(not by_id[i].finance for i in utama) < needed:
        raise Rejected("rules", f"berita utama harus memuat paling sedikit {needed} berita non-ekonomi")

    sixty_low = min(SIXTY_MIN, len(utama))
    if not sixty_low <= len(sixty) <= SIXTY_MAX:
        raise Rejected("rules", f"ringkas_60_detik berisi {len(sixty)} kalimat, harus {sixty_low}-{SIXTY_MAX}")
    ids = [i for i, _ in sixty]
    if len(set(ids)) != len(ids) or not set(ids) <= set(utama):
        raise Rejected("rules", "setiap kalimat 60 detik harus tentang berita utama yang berbeda")
    for cid, sentence in sixty:
        if words(sentence) > SIXTY_WORDS:
            raise Rejected("length", f"kalimat untuk id {cid} {words(sentence)} kata, maks {SIXTY_WORDS}")
        bad = unsupported_number(sentence, by_id[cid].cluster.get("source_text", ""))
        if bad:
            raise Rejected("number", f'angka "{bad}" di kalimat untuk id {cid} tidak ada di artikelnya')
    return Choice(utama, sixty, groups, trimmed)


def choose(summarizer, cands: Sequence[Candidate], digest_date: date,
           no_call_reason: str = "no_provider") -> Tuple[Choice, bool, List[str]]:
    """(choice, fallback used, reasons). One editor call, one retry with the
    reason; a daily quota stops at once. No summarizer: the fallback, no call,
    and `no_call_reason` says why (no provider, or the summaries' calls stopped)."""
    reasons: List[str] = []
    if summarizer is None:
        return deterministic(cands), True, [no_call_reason]
    prompt = build_prompt(cands, digest_date)
    ask = prompt
    for _ in (1, 2):
        try:
            return parse_editor(summarizer.summarize(ask), cands), False, reasons
        except QuotaExhausted:
            reasons.append("quota")
            break
        except SummarizerError as e:
            reasons.append("error")
            logger.warning(f"Editor call failed: {e}")
            ask = prompt
        except Rejected as r:
            reasons.append(r.reason)
            logger.warning(f"Editor answer refused ({r})")
            ask = prompt + RETRY.format(detail=r.detail)
    logger.warning(f"Editor fell back to the portal-count ranking ({', '.join(reasons)}).")
    return deterministic(cands), True, reasons


# ── The edition ─────────────────────────────────────────────────────────────

def reader_words(markdown: str) -> int:
    """Words a reader reads: link targets, markup and separators are not words."""
    text = re.sub(r"\]\([^)]*\)", "]", markdown)
    return sum(1 for token in text.split() if re.search(r"\w", token))


def _story(cand: Candidate) -> List[str]:
    story, links = cand.story, cand.cluster.get("links") or []
    lead = links[0] if links else None
    lines = [f"### [{_md(story.judul)}]({lead['link']})" if lead else f"### {story.judul}", "", story.inti, ""]
    lines += [f"- {p}" for p in story.poin]
    if story.poin:
        lines.append("")
    if story.mengapa_penting:
        lines.append(f"**{copy.WHY_IT_MATTERS}** {story.mengapa_penting}")
    reported = f"**{copy.REPORTED_BY.format(n=copy.angka(cand.portals))}**"
    if lead:
        reported += f" · [{copy.READ_AT.format(outlet=copy.outlet(lead['source']))}]({lead['link']})"
    return lines + [reported, ""]


def _md(text: str) -> str:
    """Square brackets would end a markdown link label early."""
    return text.replace("[", "(").replace("]", ")")


class SekilasLine(NamedTuple):
    line: str
    id: int                     # the candidate's id
    guaranteed: bool = False    # one of the day's largest stories: never trimmed by the word budget


content_words = story_words.content_words    # QA's echo probes (scripts/experiments/qa_newsletter_244) read it here


def echoes(candidate: Candidate, top: Candidate) -> bool:
    """True when `candidate` repeats the top story `top`. Their texts share
    content words (`story_words`) of two kinds: names -- a name in both texts --
    and event words, which say what happened -- a name in neither. A repeat
    shares at least ECHO_MIN_EVENT_WORDS event words and a name ("Trump tolak
    proposal damai Iran" / "Iran tegaskan diplomasi, Trump tolak proposal
    damai": Trump and Iran, and tolak/proposal/damai), or
    ECHO_MIN_EVENT_WORDS_UNNAMED event words without one.

    A shared name alone is never enough: two stories about one person or
    place ("Presiden Prabowo Subianto ...", "Gubernur Jawa Barat ...") are
    different events unless they also share what happened (SYS-86: the first
    rule counted any capitalised word, so one shared title and name hid a
    distinct story). And a word that is a name in one text says who, not what,
    in the other too: "Prabowo" opening "Prabowo melantik dua Wamenkeu ..." is
    not an event word shared with "Presiden Prabowo melantik Suyudi ..."
    (replay 2026-10-05, 10-01: that pair was hidden). Pairwise only: it hides
    one Sekilas line and never merges stories, so SYS-67's finding (shared
    words cannot group a section's clusters) does not apply."""
    mine = story_words.story_content_words(candidate.story.judul, candidate.story.sekilas)
    theirs = story_words.story_content_words(top.story.judul, top.story.inti)
    shared = set(mine) & set(theirs)
    named = {w for w in shared if mine[w] and theirs[w]}
    events = len({w for w in shared if not mine[w] and not theirs[w]})
    return events >= ECHO_MIN_EVENT_WORDS_UNNAMED or (events >= ECHO_MIN_EVENT_WORDS and bool(named))


def _sekilas(cands: Sequence[Candidate], choice: Choice) -> Tuple[List[SekilasLine], List[int]]:
    """(lines, ids hidden as echoes of a top story). A line for every summarized
    candidate that is neither a top story nor the same event as one -- by the
    editor's `duplikat` or by `echoes` -- one per duplicate group, at most
    SEKILAS_PER_SECTION per section unless it is one of the day's largest
    stories, in section order. A story without a summary is left to the full
    digest: its headline is a portal's, unchecked, and the editor never saw it,
    so it could repeat a top story (the 2026-10-04 replay showed "Kapolri
    Mutasi Sejumlah Perwira" under the Kapolri top story)."""
    by_id = {c.id: c for c in cands}
    tops = [by_id[i] for i in choice.utama]
    utama_groups = {_group_of(i, choice.groups) for i in choice.utama}
    seen_groups, per_section, lines, echoed = set(), {}, [], []
    for c in cands:
        group = _group_of(c.id, choice.groups)
        if not c.summarized or c.id in choice.utama or group in utama_groups or group in seen_groups:
            continue
        if not c.guaranteed and per_section.get(c.topic, 0) >= SEKILAS_PER_SECTION:
            continue
        if any(echoes(c, top) for top in tops):
            echoed.append(c.id)
            continue
        seen_groups.add(group)
        per_section[c.topic] = per_section.get(c.topic, 0) + 1
        lines.append(SekilasLine(f"- **{copy.SECTION_SHORT.get(c.topic, c.topic)} ·** {c.story.sekilas}", c.id,
                                 c.guaranteed))
    return lines, echoed


def render(cands: Sequence[Candidate], choice: Choice, digest_date: date, article_count: int, outlet_count: int,
           digest_stories: int) -> Tuple[str, int, List[SekilasLine]]:
    """(markdown, words, sekilas lines kept). While the edition is over
    WORD_BUDGET the lowest Sekilas line that is not one of the day's largest
    stories is dropped; top stories and guaranteed lines never are."""
    by_id = {c.id: c for c in cands}
    sekilas = _sekilas(cands, choice)[0]
    unsummarized = sum(1 for c in cands if not c.summarized)
    while True:
        markdown = _markdown(by_id, choice, sekilas, unsummarized, digest_date, article_count, outlet_count,
                             digest_stories)
        count = reader_words(markdown)
        droppable = [k for k, s in enumerate(sekilas) if not s.guaranteed]
        if count <= WORD_BUDGET or not droppable:
            if count > WORD_BUDGET:
                logger.warning(f"Edition is {count} words with nothing left to trim (budget {WORD_BUDGET}).")
            return markdown, count, sekilas
        sekilas = sekilas[:droppable[-1]] + sekilas[droppable[-1] + 1:]


def _markdown(by_id, choice: Choice, sekilas, unsummarized: int, digest_date: date, article_count: int,
              outlet_count: int, digest_stories: int) -> str:
    lines = [f"# {copy.TITLE}", "", f"> {copy.DATELINE_EDITION.format(tanggal=copy.tanggal(digest_date))}", ""]
    if unsummarized:      # candidates left out for want of a summary (SYS-84's notice, worded for the edition)
        lines += [f"> {copy.degraded_edition(unsummarized)}", ""]
    lines += [f"## {copy.SIXTY_SECONDS}", ""] + [f"- {sentence}" for _, sentence in choice.sixty] + [""]
    lines += [f"## {copy.TOP_STORIES}", ""]
    for cid in choice.utama:
        lines += _story(by_id[cid])
    if sekilas:
        lines += [f"## {copy.AT_A_GLANCE}", ""] + [s.line for s in sekilas] + [""]
    archive = copy.FOOTER_FULL_EDITION.format(n=copy.angka(digest_stories))
    lines += ["---", "", f"*{copy.footer(article_count, outlet_count)} {archive}*"]
    return "\n".join(lines) + "\n"


def build(summarizer, sections: Sequence[dict], digest_date: date, article_count: int,
          outlet_count: int, no_call_reason: str = "no_provider") -> Optional[Edition]:
    """The edition, or None when no shown story has a summary (nothing to edit)."""
    cands = candidates(sections)
    if not any(c.summarized for c in cands):
        return None          # the caller reports it (the operator's note, at ERROR)
    choice, fallback, reasons = choose(summarizer, cands, digest_date, no_call_reason)
    digest_stories = sum(len(s["clusters"]) for s in sections)
    markdown, count, sekilas = render(cands, choice, digest_date, article_count, outlet_count, digest_stories)
    by_id = {c.id: c for c in cands}
    echoed = [by_id[i].story.sekilas for i in _sekilas(cands, choice)[1]]
    if echoed:
        logger.info(f"Sekilas lines hidden as repeats of a top story: {echoed}")
    return Edition(markdown, count, len(choice.utama), len(sekilas), sum(1 for c in cands if not c.summarized),
                   fallback, reasons, choice.sixty_trimmed, echoed)


def briefing(markdown: str) -> Tuple[List[str], int]:
    """(the 60-second sentences, the number of top stories) of an edition file,
    for the Telegram message (OPS-43)."""
    sentences, top, section = [], 0, None
    for line in markdown.replace("\r\n", "\n").split("\n"):
        if line.startswith("## "):
            section = line[3:].strip()
        elif section == copy.SIXTY_SECONDS and line.startswith("- "):
            sentences.append(line[2:].strip())
        elif section == copy.TOP_STORIES and line.startswith("### "):
            top += 1
    return sentences, top
