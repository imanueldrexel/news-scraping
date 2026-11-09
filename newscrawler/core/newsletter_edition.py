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
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Dict, List, NamedTuple, Optional, Sequence, Tuple

from newscrawler.core import newsletter_copy as copy
from newscrawler.core import story_words
from newscrawler.core.filter_rubric import TOPICS_FINANCE
from newscrawler.core.llm_json import Rejected, ask_json, json_object
from newscrawler.core.source_check import unsupported_number
from newscrawler.core.story_arc import REASONS as ARC_REASONS
from newscrawler.core.story_arc import StoryArc, write_arc
from newscrawler.core.story_summary import pick_articles, words
from newscrawler.core.summarizer import QuotaExhausted, SummarizerError
from newscrawler.core.thread_finder import find_thread

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

CANDIDATES_PER_SECTION = 3
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

@dataclass(frozen=True)
class EditorPolicy:
    """SYS-149 (#339): the editor's rules in one record. `build_prompt` writes
    their numbers into the prompt and `parse_editor` / `deterministic` enforce
    the same record, so the two can never disagree. NEWSLETTER_ARCS picks the
    policy: today's 6-8 summaries, or the story arcs' 3-4 deep stories."""
    utama_min: int
    utama_max: int
    max_per_section: int
    min_non_finance: int          # when that many distinct non-finance events reached ...
    non_finance_min_portals: int  # ... this many portals (fewer qualify: fewer are asked)
    sixty_min: int
    sixty_max: int
    sixty_words: int
    fallback_utama: int           # the deterministic fallback's picks ...
    fallback_sixty: int           # ... and its 60-second sentences (their sekilas lines)


# The owner's rules of 2026-10-05 (SYS-83), unchanged.
POLICY_TODAY = EditorPolicy(utama_min=6, utama_max=8, max_per_section=2, min_non_finance=2, non_finance_min_portals=3,
                            sixty_min=3, sixty_max=5, sixty_words=18, fallback_utama=6, fallback_sixty=4)
# The story arcs (tracker #336, owner 2026-10-13): 3-4 deep stories. ">= 1 non-finance" is the scaled
# default of 2-of-6-8, flagged for the owner on SYS-149. A 60-second sentence per top story at most.
POLICY_ARCS = EditorPolicy(utama_min=3, utama_max=4, max_per_section=2, min_non_finance=1, non_finance_min_portals=3,
                           sixty_min=3, sixty_max=4, sixty_words=18, fallback_utama=4, fallback_sixty=3)
_EXAMPLE_UTAMA = (12, 3, 5, 18, 1, 9)

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
    "2. utama: pilih {utama_min}-{utama_max} id terpenting, urut dari yang terpenting. Utamakan keputusan resmi, "
    "dampak luas bagi\n"
    "   ekonomi, pasar, atau publik, dan jumlah portal yang tinggi. Maks {max_per_section} dari rubrik yang sama.\n"
    "   Satu id per peristiwa. Utamakan rubrik ekonomi, tetapi sertakan paling sedikit {min_non_finance} berita "
    "dari rubrik\n"
    "   non-ekonomi bila ada yang penting.\n"
    "3. ringkas_60_detik: {sixty_min}-{sixty_max} kalimat SAJA (bukan satu kalimat untuk setiap berita utama), "
    "masing-masing\n"
    "   maks {sixty_words} kata, tiap kalimat tentang satu berita utama yang berbeda dan terpenting, ditulis ulang dari\n"
    "   \"inti\" tanpa fakta baru.\n"
    "\n"
    "Balas HANYA dengan JSON valid:\n"
    "{{\"duplikat\": [[3, 7]], \"utama\": [{contoh_utama}],\n"
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
    # DBT-75 (#347): what the edition was built from, for replays: the candidates, the choice, the kept
    # Sekilas lines and the ids hidden as echoes. Not part of stats() (not stored in the row).
    trace: dict = field(default_factory=dict)
    # SYS-149 (#339): with the story arcs, their counts and the edition's stories (judul, terkait and
    # alur sitemap ids: SYS-151's story memory reads them). None without arcs: the row is unchanged.
    arcs: Optional[dict] = None
    stories: Optional[list] = None

    def stats(self) -> dict:
        """The `_edition` entry of newsletter_digests.categories."""
        out = {"built": True, "words": self.words, "utama": self.utama, "sekilas": self.sekilas,
               "unsummarized": self.unsummarized, "editor_fallback": self.editor_fallback,
               "editor_rejections": list(self.editor_rejections), "sixty_trimmed": self.sixty_trimmed,
               "echoes_hidden": list(self.echoes_hidden)}
        if self.arcs is not None:
            out["arcs"] = dict(self.arcs)
            out["stories"] = list(self.stories or [])
        return out


@dataclass
class ArcInputs:
    """What the story arcs (SYS-149) need from the day's plan: NEWS_L1's search
    (thread_finder), the timeline rows' lookup, and a story's centroid (the
    normalized mean L1 vector of its articles)."""
    search: Callable
    lookup: Callable
    centroid: Callable[[list], Sequence[float]]


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


def build_prompt(cands: Sequence[Candidate], digest_date: date, policy: EditorPolicy = POLICY_TODAY) -> str:
    lines = [f"{c.id} | {copy.SECTION_NAMES.get(c.topic, c.topic)} | {c.portals} | {c.story.judul} | {c.story.inti}"
             for c in cands if c.summarized]
    example = ", ".join(str(i) for i in _EXAMPLE_UTAMA[:policy.utama_min])
    return PROMPT.format(n=len(lines), tanggal=copy.tanggal(digest_date), kandidat="\n".join(lines),
                         utama_min=policy.utama_min, utama_max=policy.utama_max, max_per_section=policy.max_per_section,
                         min_non_finance=policy.min_non_finance, sixty_min=policy.sixty_min, sixty_max=policy.sixty_max,
                         sixty_words=policy.sixty_words, contoh_utama=example)


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


def _pick(pool: Sequence[Candidate], limit: int, reserve_non_finance: int, groups: Sequence[set],
          max_per_section: int = POLICY_TODAY.max_per_section) -> List[Candidate]:
    """In `pool` order: at most `max_per_section` per section and one per event;
    the best `reserve_non_finance` non-finance stories first, then finance
    stories, then the remaining non-finance ones, up to `limit`."""
    picked: List[Candidate] = []

    def fits(c):
        return (c not in picked and len(picked) < limit
                and sum(p.topic == c.topic for p in picked) < max_per_section
                and all(_group_of(p.id, groups) != _group_of(c.id, groups) for p in picked))

    for c in pool:
        if not c.finance and sum(not p.finance for p in picked) < reserve_non_finance and fits(c):
            picked.append(c)
    for wanted in (True, False):
        for c in pool:
            if c.finance == wanted and fits(c):
                picked.append(c)
    return picked


def required_non_finance(cands: Sequence[Candidate], groups: Sequence[set] = (),
                         policy: EditorPolicy = POLICY_TODAY) -> int:
    """How many non-finance top stories the rules ask for: `policy.min_non_finance`, or
    fewer when fewer distinct non-finance events reached `policy.non_finance_min_portals`."""
    eligible = {_group_of(c.id, groups) for c in cands
                if c.summarized and not c.finance and c.portals >= policy.non_finance_min_portals}
    return min(policy.min_non_finance, len(eligible))


def _by_portals(cands: Sequence[Candidate]) -> List[Candidate]:
    return sorted((c for c in cands if c.summarized), key=lambda c: (-c.portals, c.id))


def deterministic(cands: Sequence[Candidate], groups: Sequence[set] = (), policy: EditorPolicy = POLICY_TODAY) -> Choice:
    """The editor's fallback: by portal count under the same quotas, finance first;
    the 60-second block is the top `policy.fallback_sixty` stories' `sekilas` lines."""
    pool = _by_portals(cands)
    picked = _pick(pool, policy.fallback_utama, required_non_finance(cands, groups, policy), groups,
                   policy.max_per_section)
    picked.sort(key=pool.index)
    return Choice([c.id for c in picked], [(c.id, c.story.sekilas) for c in picked[:policy.fallback_sixty]],
                  list(groups))


def _ids(value, known: set, what: str) -> List[int]:
    if not isinstance(value, list) or any(not isinstance(i, int) or isinstance(i, bool) for i in value):
        raise Rejected("json", f'"{what}" harus daftar id')
    unknown = [i for i in value if i not in known]
    if unknown:
        raise Rejected("json", f'"{what}" memuat id yang tidak ada di daftar kandidat: {unknown[:3]}')
    return value


def parse_editor(answer: Optional[str], cands: Sequence[Candidate], policy: EditorPolicy = POLICY_TODAY) -> Choice:
    """The editor's answer as a Choice, or Rejected (reason json, rules, length or number)."""
    data = json_object(answer)
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
    # even with the prompt saying "3-5 kalimat SAJA". The first sixty_max are kept whole (the model
    # orders them like `utama`, most important first); nothing is cut, and the count is reported.
    trimmed = max(0, len(sixty) - policy.sixty_max)
    if trimmed:
        logger.info(f"Editor wrote {len(sixty)} 60-second sentences; keeping the first {policy.sixty_max}.")
        sixty = sixty[:policy.sixty_max]

    if len(set(utama)) != len(utama):
        raise Rejected("rules", "utama memuat id yang sama dua kali")
    capacity = len(_pick(_by_portals(cands), policy.utama_max, 0, groups, policy.max_per_section))
    low = min(policy.utama_min, capacity)
    if not low <= len(utama) <= policy.utama_max:
        raise Rejected("rules", f"utama berisi {len(utama)} id, harus {low}-{policy.utama_max}")
    for topic in {by_id[i].topic for i in utama}:
        if sum(by_id[i].topic == topic for i in utama) > policy.max_per_section:
            raise Rejected("rules", f"lebih dari {policy.max_per_section} berita utama dari rubrik "
                                    f"{copy.SECTION_NAMES.get(topic, topic)}")
    if len({_group_of(i, groups) for i in utama}) != len(utama):
        raise Rejected("rules", "dua berita utama membahas peristiwa yang sama (lihat duplikat)")
    needed = required_non_finance(cands, groups, policy)
    if sum(not by_id[i].finance for i in utama) < needed:
        raise Rejected("rules", f"berita utama harus memuat paling sedikit {needed} berita non-ekonomi")

    sixty_low = min(policy.sixty_min, len(utama))
    if not sixty_low <= len(sixty) <= policy.sixty_max:
        raise Rejected("rules", f"ringkas_60_detik berisi {len(sixty)} kalimat, harus {sixty_low}-{policy.sixty_max}")
    ids = [i for i, _ in sixty]
    if len(set(ids)) != len(ids) or not set(ids) <= set(utama):
        raise Rejected("rules", "setiap kalimat 60 detik harus tentang berita utama yang berbeda")
    for cid, sentence in sixty:
        if words(sentence) > policy.sixty_words:
            raise Rejected("length", f"kalimat untuk id {cid} {words(sentence)} kata, maks {policy.sixty_words}")
        bad = unsupported_number(sentence, by_id[cid].cluster.get("source_text", ""))
        if bad:
            raise Rejected("number", f'angka "{bad}" di kalimat untuk id {cid} tidak ada di artikelnya')
    return Choice(utama, sixty, groups, trimmed)


def choose(summarizer, cands: Sequence[Candidate], digest_date: date,
           no_call_reason: str = "no_provider", policy: EditorPolicy = POLICY_TODAY) -> Tuple[Choice, bool, List[str]]:
    """(choice, fallback used, reasons). One editor call, one retry with the
    reason (a failed call is retried without one); a daily quota stops at once
    (`llm_json.ask_json`, on_error="retry"). No summarizer: the fallback, no
    call, and `no_call_reason` says why (no provider, or the summaries' calls stopped)."""
    if summarizer is None:
        return deterministic(cands, policy=policy), True, [no_call_reason]
    outcome = ask_json(summarizer, build_prompt(cands, digest_date, policy),
                       lambda answer, attempt: parse_editor(answer, cands, policy),
                       on_error="retry", label="Editor answer")
    reasons = outcome.reasons
    if outcome.value is not None:
        return outcome.value, False, reasons
    logger.warning(f"Editor fell back to the portal-count ranking ({', '.join(reasons)}).")
    return deterministic(cands, policy=policy), True, reasons


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


def _prose_story(cand: Candidate, arc: Optional[StoryArc]) -> List[str]:
    """SYS-149 (owner 2026-10-13: pure prose, no labels): the arc's judul and
    its paragraphs (today, then the back-story closed by the agenda); a story
    whose arc failed is its summary as prose (inti and poin, then why it matters)."""
    story, links = cand.story, cand.cluster.get("links") or []
    lead = links[0] if links else None
    judul = arc.judul if arc else story.judul
    if arc:
        paragraphs = arc.prose.split("\n\n")
    else:
        paragraphs = [p for p in (" ".join([story.inti] + list(story.poin)), story.mengapa_penting) if p]
    lines = [f"### [{_md(judul)}]({lead['link']})" if lead else f"### {judul}", ""]
    for paragraph in paragraphs:
        lines += [paragraph, ""]
    reported = f"**{copy.REPORTED_BY.format(n=copy.angka(cand.portals))}**"
    if lead:
        reported += f" · [{copy.READ_AT.format(outlet=copy.outlet(lead['source']))}]({lead['link']})"
    return lines + [reported, ""]


def write_arcs(summarizer, cands: Sequence[Candidate], choice: "Choice", digest_date: date,
               inputs: ArcInputs) -> Tuple[Dict[int, StoryArc], dict, list]:
    """(arcs by candidate id, the arcs' stats, the trace) for the top stories.
    Each: thread_finder over NEWS_L1 from the centroid of the story's related
    articles (excluding today's own), then one arc call and one retry
    (story_arc). A refused arc, or a failed call, leaves that story to its
    summary as prose; a quota stops the arcs."""
    stats = {"built": 0, "fallback": 0, "refusals": {r: 0 for r in ARC_REASONS}, "alur_items": 0,
             "no_history": 0, "agenda": 0, "demoted": 0, "errors": 0, "stopped": None}
    by_id = {c.id: c for c in cands}
    arcs: Dict[int, StoryArc] = {}
    trace = []
    for cid in choice.utama:
        cand = by_id[cid]
        cluster = cand.cluster
        related = cluster.get("related") or cluster["articles"]
        shown = pick_articles(cluster["articles"])
        timeline = find_thread(inputs.centroid(related), digest_date, [a["sitemap_id"] for a in cluster["articles"]],
                               inputs.search, inputs.lookup)
        rejections: list = []
        arc = None
        if stats["stopped"] is None:
            try:
                arc = write_arc(summarizer, shown, timeline, digest_date, rejections)
            except QuotaExhausted:
                stats["stopped"] = "quota"
                logger.warning("Arc calls stopped: the daily quota is spent; the rest are summaries as prose.")
            except SummarizerError as e:
                stats["errors"] += 1
                logger.warning(f"Arc call failed for {cand.story.judul!r}: {e}")
        for reason in rejections:
            stats["refusals"][reason] += 1
        if arc is None:
            stats["fallback"] += 1
        else:
            arcs[cid] = arc
            stats["built"] += 1
            stats["alur_items"] += len(arc.alur_items)
            stats["no_history"] += not arc.alur_items
            stats["agenda"] += bool(arc.agenda)
            stats["demoted"] += arc.demoted_alur
        trace.append({"id": cid, "timeline": timeline, "reasons": rejections, "arc": arc})
    return arcs, stats, trace


def _stories(cands: Sequence[Candidate], choice: "Choice", arcs: Dict[int, StoryArc]) -> list:
    """The edition's top stories as SYS-151's story memory reads them."""
    by_id = {c.id: c for c in cands}
    out = []
    for cid in choice.utama:
        cand, arc = by_id[cid], arcs.get(cid)
        related = cand.cluster.get("related") or cand.cluster["articles"]
        out.append({"judul": arc.judul if arc else cand.story.judul,
                    "terkait_ids": [a["sitemap_id"] for a in related],
                    "alur_ids": [t.sitemap_id for t in arc.alur_items] if arc else [],
                    "arc": arc is not None})
    return out


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
           digest_stories: int, arcs: Optional[Dict[int, StoryArc]] = None
           ) -> Tuple[str, int, List[SekilasLine]]:
    """(markdown, words, sekilas lines kept). While the edition is over
    WORD_BUDGET the lowest Sekilas line that is not one of the day's largest
    stories is dropped; top stories and guaranteed lines never are. With the
    story arcs (`arcs` given, SYS-149) the stories are prose, and once no Sekilas
    line is left to drop the last top story beyond POLICY_ARCS.utama_min becomes
    a Sekilas line (`choice` is then changed in place: the caller reports it)."""
    by_id = {c.id: c for c in cands}
    sekilas = _sekilas(cands, choice)[0]
    unsummarized = sum(1 for c in cands if not c.summarized)
    while True:
        markdown = _markdown(by_id, choice, sekilas, unsummarized, digest_date, article_count, outlet_count,
                             digest_stories, arcs)
        count = reader_words(markdown)
        droppable = [k for k, s in enumerate(sekilas) if not s.guaranteed]
        if count <= WORD_BUDGET:
            return markdown, count, sekilas
        if droppable:
            sekilas = sekilas[:droppable[-1]] + sekilas[droppable[-1] + 1:]
            continue
        if arcs is not None and len(choice.utama) > POLICY_ARCS.utama_min:
            last = choice.utama.pop()
            choice.sixty[:] = [(i, sentence) for i, sentence in choice.sixty if i != last]
            logger.info(f"Edition over budget: top story {by_id[last].story.judul!r} moved to Sekilas.")
            sekilas = [s._replace(guaranteed=True) if s.id == last else s for s in _sekilas(cands, choice)[0]]
            continue
        logger.warning(f"Edition is {count} words with nothing left to trim (budget {WORD_BUDGET}).")
        return markdown, count, sekilas


def _markdown(by_id, choice: Choice, sekilas, unsummarized: int, digest_date: date, article_count: int,
              outlet_count: int, digest_stories: int, arcs: Optional[Dict[int, StoryArc]] = None) -> str:
    lines = [f"# {copy.TITLE}", "", f"> {copy.DATELINE_EDITION.format(tanggal=copy.tanggal(digest_date))}", ""]
    if unsummarized:      # candidates left out for want of a summary (SYS-84's notice, worded for the edition)
        lines += [f"> {copy.degraded_edition(unsummarized)}", ""]
    lines += [f"## {copy.SIXTY_SECONDS}", ""] + [f"- {sentence}" for _, sentence in choice.sixty] + [""]
    lines += [f"## {copy.TOP_STORIES}", ""]
    for cid in choice.utama:
        lines += _story(by_id[cid]) if arcs is None else _prose_story(by_id[cid], arcs.get(cid))
    if sekilas:
        lines += [f"## {copy.AT_A_GLANCE}", ""] + [s.line for s in sekilas] + [""]
    archive = copy.FOOTER_FULL_EDITION.format(n=copy.angka(digest_stories))
    lines += ["---", "", f"*{copy.footer(article_count, outlet_count, arcs=arcs is not None)} {archive}*"]
    return "\n".join(lines) + "\n"


def build(summarizer, sections: Sequence[dict], digest_date: date, article_count: int,
          outlet_count: int, no_call_reason: str = "no_provider",
          arcs: Optional[ArcInputs] = None) -> Optional[Edition]:
    """The edition, or None when no shown story has a summary (nothing to edit).
    `arcs` (SYS-149, NEWSLETTER_ARCS): the 3-4 top stories told as arcs, in
    prose; None is today's edition, byte for byte."""
    cands = candidates(sections)
    if not any(c.summarized for c in cands):
        return None          # the caller reports it (the operator's note, at ERROR)
    policy = POLICY_TODAY if arcs is None else POLICY_ARCS
    choice, fallback, reasons = choose(summarizer, cands, digest_date, no_call_reason, policy)
    written, arc_stats, arc_trace = None, None, None
    if arcs is not None:
        if summarizer is None:
            written, arc_trace = {}, []
            arc_stats = {"built": 0, "fallback": len(choice.utama), "refusals": {r: 0 for r in ARC_REASONS},
                         "alur_items": 0, "no_history": 0, "agenda": 0, "demoted": 0, "errors": 0,
                         "stopped": no_call_reason}
        else:
            written, arc_stats, arc_trace = write_arcs(summarizer, cands, choice, digest_date, arcs)
    digest_stories = sum(len(s["clusters"]) for s in sections)
    markdown, count, sekilas = render(cands, choice, digest_date, article_count, outlet_count, digest_stories,
                                      written)
    by_id = {c.id: c for c in cands}
    hidden = _sekilas(cands, choice)[1]
    echoed = [by_id[i].story.sekilas for i in hidden]
    if echoed:
        logger.info(f"Sekilas lines hidden as repeats of a top story: {echoed}")
    trace = {"candidates": cands, "choice": choice, "kept": sekilas, "echoes": hidden}
    stories = None
    if written is not None:
        trace["arcs"] = arc_trace
        stories = _stories(cands, choice, written)
    return Edition(markdown, count, len(choice.utama), len(sekilas), sum(1 for c in cands if not c.summarized),
                   fallback, reasons, choice.sixty_trimmed, echoed, trace=trace, arcs=arc_stats, stories=stories)


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
