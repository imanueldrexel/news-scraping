#!/usr/bin/env python3
"""
SYS-36 (#120): build the importance-filter gold set -- a stratified,
reject-inclusive sample of `sitemaps` rows labelled by Gemini against the
written news-worthy rubric (`newscrawler/core/filter_rubric.py`).

Five steps, each its own subcommand so the expensive/irreversible ones can be
re-run alone:

  sample          Read-only. Pull every sitemap (+ articles.extracted_text[:500]
                  where saved), assign each row ONE stratum, draw a seeded,
                  stratified sample and write tests/fixtures/filter_gold_sample.jsonl.
                  Freezes the population: run it BEFORE the SYS-35 re-queue and
                  the SYS-34/SRC-36 cleanup, both of which change the strata --
                  and AFTER any category rewrite (SYS-44: the 2026-09-20 sample
                  was drawn 40 min before fix_url_shaped_categories.py and
                  carried 336 stale URL categories until `refresh`).
                  Rows whose headline is a URL-slug placeholder (SYS-33: TIRTO/
                  TEMPO before the repair) are excluded and counted. SYS-43: the
                  population is collapsed to one row per normalised headline
                  within a source first (INEWS's 113 regional mirror hosts list
                  the same syndicated article once per host; the round-robin
                  over cells drew it once per host -- 319 rows / 164 headlines).
                  A re-draw today CANNOT reproduce the 2026-09-20 strata: the
                  finance_reject population was re-queued and saved (SYS-35) and
                  the soft_save rows were deleted (SYS-34). Refresh the committed
                  sample; only re-draw for a deliberately new population.
  refresh         Repair the committed sample + gold in place (SYS-43/SYS-44):
                  re-read `category` from the DB by sitemap_id, re-run the
                  stratum assignment on the frozen crawl_status/has_body, drop
                  duplicate headlines within a source (keep the row with a body,
                  else the lowest sitemap_id), move any headline group that
                  spans train/test wholly to train, and strip the label from any
                  headline group the labeller labelled both ways so `label`
                  re-labels it in one batch. Labels of every other row are
                  untouched. --dry-run prints the counts and writes nothing.
  merge-bodies    SYS-47: fold tests/fixtures/filter_gold_bodies.jsonl (from
                  scripts/experiments/fetch_gold_bodies.py) into the sample and
                  gold: rows that gained a body get body_head/has_body and lose
                  their headline-only label so `label` re-decides them on
                  title + body; `had_body_at_freeze` keeps the stratum frozen.
  label           An LLM labels --batch-size rows per call, JSON out, counted in
                  api_usage_log under the model's name (the same daily cap as
                  knowledge extraction). --provider openai (default; OPS-20 #136:
                  any OpenAI-compatible endpoint -- OPENAI_API_KEY, OPENAI_BASE_URL,
                  OPENAI_MODEL, e.g. SumoPod's deepseek-v4-flash) or --provider
                  gemini (the existing google.genai client; free tier is 20
                  calls/day/model). Resumable: rows already in the output are
                  skipped; a row whose label comes back invalid is left for the
                  next run. --dry-run needs no key and writes nothing;
                  --max-calls N is the smoke test; --workers N overlaps calls.
  handcheck       Write tests/fixtures/filter_gold_handcheck.csv: 100 rows across
                  strata for is_news + 50 news rows across topics for topic, with
                  blank human_* columns for the owner.
  score-handcheck Agreement on the filled-in CSV (>= 95% is_news, >= 85% topic
                  to accept; otherwise amend the rubric and re-label).
  stats           Label distribution per stratum / topic / source / split.

Output row (tests/fixtures/filter_gold.jsonl, one JSON object per line):
  sitemap_id, source, category, headline, body_head (nullable), has_body,
  stratum, split ("train"/"test", fixed 80/20 per stratum, seeded),
  is_news, topic, labeller, labelled_at

Usage:
    python scripts/label_filter_gold.py sample [--size 4000] [--seed 20260920]
    python scripts/label_filter_gold.py refresh --dry-run
    python scripts/label_filter_gold.py refresh
    python scripts/label_filter_gold.py label --dry-run
    python scripts/label_filter_gold.py label --max-calls 2
    python scripts/label_filter_gold.py label
    python scripts/label_filter_gold.py handcheck
    python scripts/label_filter_gold.py score-handcheck
    python scripts/label_filter_gold.py stats
"""
import argparse
import collections
import csv
import json
import logging
import os
import random
import re
import sys
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from newscrawler.core.filter_rubric import TOPICS, TOPICS_NEWS, TOPICS_FINANCE, build_label_prompt, is_valid_label
from newscrawler.core.importance_filter import category_gate, is_finance_category, is_offtopic_category

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(REPO_ROOT, "tests", "fixtures")
SAMPLE_PATH = os.path.join(FIXTURES, "filter_gold_sample.jsonl")
GOLD_PATH = os.path.join(FIXTURES, "filter_gold.jsonl")
HANDCHECK_PATH = os.path.join(FIXTURES, "filter_gold_handcheck.csv")

BODY_HEAD_CHARS = 500
TEST_FRACTION = 0.2

# ── Strata ───────────────────────────────────────────────────────────────────
# First match wins. Sizes are targets for a 4,000-row sample; a stratum with
# fewer rows than its target contributes all of them and the shortfall is
# redistributed to `mixed_bucket` (the population SYS-37's precision gate is
# measured on).
STRATA_TARGETS: List[Tuple[str, int]] = [
    ("finance_reject",         600),   # SYS-35: finance section, rejected_filter -- all news, score said no
    ("soft_save",              200),   # SYS-34: a soft category that produced a saved article
    ("religion_boundary",      200),   # doa/kajian/khutbah vs kemenag/haji
    ("econ_politics_boundary", 400),   # menteri/menkeu/bahlil/dpr/pilkada/partai -- topic-tag quality
    ("viva_general",           500),   # VIVA's non-bisnis sections: what widened crawlers will list (SRC-34)
    ("mixed_bucket",           900),   # news/berita/news-sitemap/regional subdomains: the score decides today
    ("finance_saved",          400),   # finance section, saved (has body)
    ("finance_pending",        150),   # finance section, never fetched
    ("hard_news",              400),   # nasional/politik/hukum/daerah/... any status
    ("soft_category",          200),   # a denied category, no article
    ("other",                   50),
]
STRATUM_ORDER = [name for name, _ in STRATA_TARGETS]

_RELIGION_RE = re.compile(r"\b(doa|kajian|khutbah|tausiyah|kemenag|haji|umrah|umroh|ramadan|ramadhan)\b", re.I)
_ECON_POLITICS_RE = re.compile(
    r"\b(menteri|menkeu|menhub|menko|bahlil|kemenkeu|kemenperin|dpr|dprd|pilkada|partai|prabowo|gibran|gubernur|bupati)\b",
    re.I,
)
_MIXED_NAMES = {"news", "berita", "news-sitemap", "sitemap", "breaking-news", "artikel", "features", "ragam", "trending"}


def assign_stratum(source: str, category: Optional[str], crawl_status: str, has_body: bool, headline: str) -> str:
    cat = (category or "").strip()
    gate = category_gate(cat)
    finance = is_finance_category(cat)
    if finance and crawl_status == "rejected_filter" and not has_body:
        return "finance_reject"
    if has_body and is_offtopic_category(cat):
        return "soft_save"
    if _RELIGION_RE.search(headline or ""):
        return "religion_boundary"
    if _ECON_POLITICS_RE.search(headline or ""):
        return "econ_politics_boundary"
    if source == "VIVA" and not finance:
        return "viva_general"
    if gate is None and (cat.lower() in _MIXED_NAMES or cat.lower().startswith("http") or not cat):
        return "mixed_bucket"
    if finance and has_body:
        return "finance_saved"
    if finance:
        return "finance_pending"
    if gate == "allow":
        return "hard_news"
    if gate == "deny":
        return "soft_category"
    if gate is None:
        # A named section the gate cannot place (KOMPAS regional cities,
        # PIKIRANRAKYAT brands, tech/health/opinion desks): a mixed bucket too.
        return "mixed_bucket"
    return "other"


def allocate(counts: Dict[str, int], size: int) -> Dict[str, int]:
    """Targets scaled to `size`, capped at availability, shortfall to mixed_bucket."""
    scale = size / sum(t for _, t in STRATA_TARGETS)
    alloc = {}
    shortfall = 0
    for name, target in STRATA_TARGETS:
        want = int(round(target * scale))
        have = counts.get(name, 0)
        alloc[name] = min(want, have)
        shortfall += want - alloc[name]
    if shortfall > 0:
        spare = counts.get("mixed_bucket", 0) - alloc.get("mixed_bucket", 0)
        alloc["mixed_bucket"] = alloc.get("mixed_bucket", 0) + min(shortfall, max(spare, 0))
    return alloc


def draw(rows: List[dict], n: int, rng: random.Random) -> List[dict]:
    """n rows from one stratum, round-robin over (source, category, status)
    cells so a 1,000-row VIVA `blog` cell cannot crowd out a 20-row one."""
    cells: Dict[Tuple, List[dict]] = collections.defaultdict(list)
    for r in rows:
        cells[(r["source"], r["category"], r["crawl_status"])].append(r)
    for cell in cells.values():
        rng.shuffle(cell)
    keys = sorted(cells)
    rng.shuffle(keys)
    out: List[dict] = []
    while len(out) < n and keys:
        next_keys = []
        for k in keys:
            if cells[k]:
                out.append(cells[k].pop())
                if len(out) >= n:
                    break
            if cells[k]:
                next_keys.append(k)
        keys = next_keys
    return out


def normalise_headline(headline: Optional[str]) -> str:
    """The identity of an article's text for dedup purposes: case- and
    whitespace-insensitive. Two rows with the same normalised headline are
    the same example whatever host or section they were listed under."""
    return re.sub(r"\s+", " ", (headline or "").strip().lower())


def _prefer(a: dict, b: dict) -> dict:
    """Of two rows with the same headline in the same source, keep the one
    with a body (more text for the labeller and the probe), else the lowest
    sitemap_id (the first listing; the mirrors came later)."""
    if bool(a.get("has_body")) != bool(b.get("has_body")):
        return a if a.get("has_body") else b
    return a if a["sitemap_id"] <= b["sitemap_id"] else b


def dedupe_within_source(rows: List[dict]) -> Tuple[List[dict], List[dict]]:
    """SYS-43 (#138): one row per (source, normalised headline). Returns
    (kept, dropped) in the input order of the kept rows. Cross-source repeats
    (wire copy on two outlets) are kept -- they are distinct listings of the
    same text and assign_splits keeps them on one side of the split."""
    best: Dict[Tuple[str, str], dict] = {}
    for r in rows:
        key = (r["source"], normalise_headline(r["headline"]))
        best[key] = _prefer(best[key], r) if key in best else r
    keep_ids = {id(r) for r in best.values()}
    kept = [r for r in rows if id(r) in keep_ids]
    dropped = [r for r in rows if id(r) not in keep_ids]
    return kept, dropped


def assign_splits(rows: List[dict], rng: random.Random, test_fraction: float = TEST_FRACTION) -> None:
    """Fixed 80/20 within each stratum, in place. SYS-43: rows that share a
    normalised headline (across sources and strata) always land on the same
    side -- a test row whose text is also in train measures memory, not the
    classifier. A group already placed by an earlier stratum keeps its side
    and counts toward this stratum's quota."""
    by_stratum: Dict[str, List[dict]] = collections.defaultdict(list)
    for r in rows:
        by_stratum[r["stratum"]].append(r)
    side_of: Dict[str, str] = {}
    for stratum_rows in by_stratum.values():
        rng.shuffle(stratum_rows)
        n_test = int(round(len(stratum_rows) * test_fraction))
        # Groups an earlier stratum already placed count toward this quota.
        n_test -= sum(1 for r in stratum_rows if side_of.get(normalise_headline(r["headline"])) == "test")
        for r in stratum_rows:
            key = normalise_headline(r["headline"])
            if key in side_of:
                r["split"] = side_of[key]
                continue
            r["split"] = "test" if n_test > 0 else "train"
            if r["split"] == "test":
                n_test -= 1
            side_of[key] = r["split"]


def headline_groups(rows: List[dict]) -> Dict[str, List[dict]]:
    """Rows keyed by normalised headline; only groups of two or more."""
    groups: Dict[str, List[dict]] = collections.defaultdict(list)
    for r in rows:
        groups[normalise_headline(r["headline"])].append(r)
    return {k: v for k, v in groups.items() if len(v) > 1}


def repair_split_leaks(rows: List[dict]) -> int:
    """SYS-43: for a committed sample, any headline group that spans both
    splits moves wholly to train (test shrinks by a few rows; it never gains
    a row it could have memorised). Returns rows moved."""
    moved = 0
    for group in headline_groups(rows).values():
        if len({r["split"] for r in group}) > 1:
            for r in group:
                if r["split"] != "train":
                    r["split"] = "train"
                    moved += 1
    return moved


def conflicting_label_headlines(gold_rows: List[dict]) -> List[str]:
    """SYS-43: normalised headlines the labeller labelled both ways. A row
    that survives dedup out of such a group carries a label decided by which
    batch it landed in, so it is re-labelled rather than kept."""
    return sorted(
        key for key, group in headline_groups(gold_rows).items()
        if len({bool(r["is_news"]) for r in group}) > 1
    )


def frozen_has_body(row: dict) -> bool:
    """SYS-47: the stratum is a property of the population at sample time, so
    it is computed from whether the row had a body THEN -- `had_body_at_freeze`
    -- not from `has_body`, which the body fetch may have flipped since."""
    return bool(row.get("had_body_at_freeze", row.get("has_body")))


def merge_bodies(sample: List[dict], gold: List[dict], fetched: List[dict]) -> Tuple[List[dict], List[dict], Dict[str, int]]:
    """SYS-47 (#143): fold fetched body heads into the sample and gold rows.
    Pure. For every row: `had_body_at_freeze` is set (once) from the current
    `has_body`. A row that had no body and now has one gets `body_head`/
    `has_body` updated in the sample and is DROPPED from gold -- its label was
    decided on the headline alone and must be re-decided on title + body
    (`label` picks it up). Rows that already had a body are never touched."""
    heads = {f["sitemap_id"]: f["body_head"] for f in fetched if f.get("body_head")}
    counts = {"rows_with_fetched_body": len(heads), "sample_rows_updated": 0, "gold_rows_unlabelled_for_relabel": 0,
              "fetched_for_rows_that_already_had_a_body": 0}
    gained = set()
    for r in sample:
        r.setdefault("had_body_at_freeze", bool(r.get("has_body")))
        head = heads.get(r["sitemap_id"])
        if head is None:
            continue
        if r.get("has_body"):
            counts["fetched_for_rows_that_already_had_a_body"] += 1
            continue
        r["body_head"], r["has_body"] = head, True
        gained.add(r["sitemap_id"])
        counts["sample_rows_updated"] += 1
    new_gold = []
    for g in gold:
        g.setdefault("had_body_at_freeze", bool(g.get("has_body")))
        if g["sitemap_id"] in gained:
            counts["gold_rows_unlabelled_for_relabel"] += 1
            continue
        new_gold.append(g)
    return sample, new_gold, counts


def refresh_categories(rows: List[dict], current_category_by_id: Dict[int, Optional[str]]) -> int:
    """SYS-44 (#139): overwrite `category` with the DB's current value for the
    same sitemap_id (a repair script may have rewritten it since the sample
    was drawn). Rows the DB no longer has are left alone. Returns rows changed."""
    changed = 0
    for r in rows:
        if r["sitemap_id"] not in current_category_by_id:
            continue
        current = current_category_by_id[r["sitemap_id"]]
        if (current or "") != (r.get("category") or ""):
            r["category"] = current
            changed += 1
    return changed


def reassign_strata(rows: List[dict]) -> int:
    """SYS-44: recompute `stratum` from the (possibly refreshed) category and
    the frozen crawl_status / has_body / headline. Returns rows changed."""
    changed = 0
    for r in rows:
        stratum = assign_stratum(r["source"], r.get("category"), r["crawl_status"], frozen_has_body(r), r["headline"])
        if stratum != r.get("stratum"):
            r["stratum"] = stratum
            changed += 1
    return changed


# ── DB ───────────────────────────────────────────────────────────────────────
_ALL_ROWS_SQL = """
    SELECT s.sitemap_id, s.sources AS source, s.category, s.headline, s.link, s.crawl_status,
           LEFT(a.extracted_text, :n) AS body_head
    FROM sitemaps s LEFT JOIN articles a ON a.sitemap_id = s.sitemap_id
"""


def load_population(session) -> Tuple[List[dict], int, int]:
    """Every sitemap row as a dict, minus placeholder-headline rows and minus
    same-source duplicate headlines (SYS-43). Returns (rows, placeholders
    excluded, duplicates collapsed)."""
    from sqlalchemy import text
    from newscrawler.domain.dtos.dataflow.details.site_map_dto import SitemapDTO
    from newscrawler.infrastructure.datasource.scrapers.crawler import Crawler

    rows = []
    placeholders = 0
    for r in session.execute(text(_ALL_ROWS_SQL), {"n": BODY_HEAD_CHARS}).fetchall():
        headline = (r.headline or "").strip()
        if not headline:
            continue
        dto = SitemapDTO(headline=headline, link=r.link, sources=r.source, sitemap_id=r.sitemap_id)
        if Crawler._is_placeholder_headline(dto):
            placeholders += 1
            continue
        body = (r.body_head or "").strip() or None
        rows.append({
            "sitemap_id": r.sitemap_id, "source": r.source, "category": r.category,
            "headline": headline, "crawl_status": r.crawl_status,
            "body_head": body, "has_body": body is not None,
        })
    rows, dropped = dedupe_within_source(rows)
    return rows, placeholders, len(dropped)


def current_categories(session, sitemap_ids: List[int]) -> Dict[int, Optional[str]]:
    from sqlalchemy import text
    rows = session.execute(
        text("SELECT sitemap_id, category FROM sitemaps WHERE sitemap_id = ANY(:ids)"), {"ids": list(sitemap_ids)}
    ).fetchall()
    return {r.sitemap_id: r.category for r in rows}


def sources_with_named_branches() -> List[str]:
    """Sources whose crawler names every branch (`branch_name_from_url`) --
    a URL-shaped category on one of these is stale, never current."""
    from newscrawler.core.crawler_dict_list import CRAWLER_DICT
    return sorted(name for name, crawler in CRAWLER_DICT.items() if hasattr(crawler, "branch_name_from_url"))


# ── JSONL helpers ────────────────────────────────────────────────────────────
def read_jsonl(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: str, rows: Iterable[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def append_jsonl(path: str, rows: Iterable[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ── Labelling ────────────────────────────────────────────────────────────────
def batch_payload(batch: List[dict]) -> str:
    return json.dumps(
        [{"id": r["sitemap_id"], "headline": r["headline"], "body_head": r["body_head"]} for r in batch],
        ensure_ascii=False,
    )


def parse_labels(raw: Optional[str], batch: List[dict]) -> Tuple[Dict[int, Tuple[bool, str]], List[str]]:
    """{sitemap_id: (is_news, topic)} for every valid, matching label; plus a
    list of reasons for the rows that were not accepted."""
    problems: List[str] = []
    if not raw:
        return {}, ["empty response"]
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return {}, [f"JSON parse error: {e}"]
    if isinstance(data, dict):
        data = data.get("labels") or data.get("rows") or [data]
    if not isinstance(data, list):
        return {}, ["response is not a JSON array"]
    wanted = {r["sitemap_id"] for r in batch}
    labels: Dict[int, Tuple[bool, str]] = {}
    for item in data:
        if not isinstance(item, dict):
            problems.append("non-object item")
            continue
        try:
            sid = int(item.get("id"))
        except (TypeError, ValueError):
            problems.append(f"bad id {item.get('id')!r}")
            continue
        if sid not in wanted:
            problems.append(f"unknown id {sid}")
            continue
        is_news, topic = item.get("is_news"), item.get("topic")
        if isinstance(is_news, str):
            is_news = {"true": True, "false": False}.get(is_news.strip().lower())
        if not is_valid_label(is_news, topic):
            problems.append(f"id {sid}: invalid label is_news={item.get('is_news')!r} topic={topic!r}")
            continue
        labels[sid] = (is_news, topic)
    for sid in wanted - labels.keys():
        if not any(str(sid) in p for p in problems):
            problems.append(f"id {sid}: missing from response")
    return labels, problems


class GeminiLabeller:
    """Thin wrapper over the same google.genai client and api_usage_log
    accounting knowledge extraction uses, so the DAILY_API_CALL_LIMIT is one
    budget for both."""

    def __init__(self, ds, model_name: str, api_key: str, daily_limit: int):
        from google import genai
        self.ds = ds
        self.model_name = model_name
        self.daily_limit = daily_limit
        self.client = genai.Client(api_key=api_key)

    def budget_left(self) -> int:
        return self.daily_limit - self.ds.get_today_api_call_count(self.model_name)

    def call(self, prompt: str) -> Optional[str]:
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        # Counted only once the API answered -- OPS-09's rule for extraction:
        # a 429/5xx/timeout never produced a response and must not eat budget.
        self.ds.increment_api_call_count(self.model_name)
        return response.text


class OpenAICompatLabeller:
    """OPS-20 (#136): any OpenAI-compatible chat endpoint (SumoPod's
    `deepseek-v4-flash` today) behind the same call()/budget_left() interface
    and the same api_usage_log accounting, keyed by model name so its calls
    are counted separately from Gemini's. Temperature 0: a labeller should
    be as deterministic as the model allows."""

    def __init__(self, ds, model_name: str, api_key: str, base_url: Optional[str], daily_limit: int):
        from openai import OpenAI
        self.ds = ds
        self.model_name = model_name
        self.daily_limit = daily_limit
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def budget_left(self) -> int:
        return self.daily_limit - self.ds.get_today_api_call_count(self.model_name)

    def call(self, prompt: str) -> Optional[str]:
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=4000,
            # deepseek-v4-flash is a reasoning model: with thinking on it spent
            # all 4,000 output tokens in reasoning_content on a 20-row batch
            # and returned an empty answer (finish=length). Off: 420 output
            # tokens, 2.4 s, 20/20 labels. An endpoint that does not know the
            # field ignores it.
            extra_body={"thinking": {"type": "disabled"}},
        )
        self.ds.increment_api_call_count(self.model_name)
        return response.choices[0].message.content


def make_labeller(provider: str):
    """The labelling client for --provider, from constants.py (env)."""
    from newscrawler.core.constants import (
        DAILY_API_CALL_LIMIT, GEMINI_API_KEY, GEMINI_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL,
    )
    from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_knowledge_data_source import (
        SQLAlchemyKnowledgeDataSource,
    )
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

    ds = SQLAlchemyKnowledgeDataSource(SQLAlchemyClient())
    if provider == "gemini":
        if not GEMINI_API_KEY:
            raise SystemExit("GEMINI_API_KEY is not set")
        return GeminiLabeller(ds, GEMINI_MODEL, GEMINI_API_KEY, DAILY_API_CALL_LIMIT), GEMINI_MODEL
    if provider == "openai":
        if not OPENAI_API_KEY:
            raise SystemExit("OPENAI_API_KEY is not set (OPENAI_BASE_URL / OPENAI_MODEL alongside it in .env)")
        return OpenAICompatLabeller(ds, OPENAI_MODEL, OPENAI_API_KEY, OPENAI_BASE_URL, DAILY_API_CALL_LIMIT), OPENAI_MODEL
    raise SystemExit(f"unknown provider {provider!r}")


# ── Subcommands ──────────────────────────────────────────────────────────────
def cmd_sample(args) -> int:
    from sqlalchemy import text
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

    rng = random.Random(args.seed)
    client = SQLAlchemyClient()
    with client.get_session() as session:
        logger.info("database: %s", session.execute(text("SELECT current_database()")).scalar())
        population, placeholders, duplicates = load_population(session)
    logger.info("%d rows in population (%d URL-slug placeholder headlines excluded -- SYS-33; "
                "%d same-source duplicate headlines collapsed -- SYS-43)", len(population), placeholders, duplicates)

    by_stratum: Dict[str, List[dict]] = collections.defaultdict(list)
    for r in population:
        r["stratum"] = assign_stratum(r["source"], r["category"], r["crawl_status"], r["has_body"], r["headline"])
        by_stratum[r["stratum"]].append(r)
    counts = {k: len(v) for k, v in by_stratum.items()}
    alloc = allocate(counts, args.size)
    logger.info("%-24s %10s %8s", "stratum", "available", "sampled")
    for name in STRATUM_ORDER:
        logger.info("%-24s %10d %8d", name, counts.get(name, 0), alloc.get(name, 0))

    sample: List[dict] = []
    for name in STRATUM_ORDER:
        sample.extend(draw(by_stratum.get(name, []), alloc.get(name, 0), rng))
    assign_splits(sample, rng)
    sample.sort(key=lambda r: r["sitemap_id"])
    write_jsonl(args.out, sample)
    n_body = sum(1 for r in sample if r["has_body"])
    n_test = sum(1 for r in sample if r["split"] == "test")
    logger.info("Wrote %d rows to %s (%d with body, %d test / %d train)",
                len(sample), args.out, n_body, n_test, len(sample) - n_test)
    return 0


def refresh_rows(sample: List[dict], gold: List[dict], current_category_by_id: Dict[int, Optional[str]]) -> Tuple[List[dict], List[dict], Dict[str, int]]:
    """The whole SYS-43/SYS-44 repair as a pure function over the two files'
    rows. Returns (new_sample, new_gold, counts). Order of operations matters:
    conflicts are detected on the gold rows BEFORE dedup (the disagreeing
    copies are what prove the label is batch-dependent), the category is
    refreshed before the stratum is recomputed, and the split leak repair
    runs on the deduped sample so within-source copies are already gone."""
    counts: Dict[str, int] = {}
    conflicts = set(conflicting_label_headlines(gold))
    counts["conflicting_headline_groups"] = len(conflicts)

    sample_by_id = {r["sitemap_id"]: r for r in sample}
    counts["categories_refreshed"] = refresh_categories(sample, current_category_by_id)
    counts["strata_reassigned"] = reassign_strata(sample)

    kept, dropped = dedupe_within_source(sample)
    counts["duplicate_rows_dropped"] = len(dropped)
    counts["split_rows_moved_to_train"] = repair_split_leaks(kept)

    kept_ids = {r["sitemap_id"] for r in kept}
    new_gold = []
    unlabelled = 0
    for g in gold:
        if g["sitemap_id"] not in kept_ids:
            continue
        if normalise_headline(g["headline"]) in conflicts:
            unlabelled += 1
            continue
        s = sample_by_id[g["sitemap_id"]]
        g = dict(g, category=s.get("category"), stratum=s["stratum"], split=s["split"])
        new_gold.append(g)
    counts["gold_rows_unlabelled_for_relabel"] = unlabelled
    counts["sample_rows"] = len(kept)
    counts["gold_rows"] = len(new_gold)
    return kept, new_gold, counts


def cmd_refresh(args) -> int:
    from sqlalchemy import text
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient

    sample = read_jsonl(args.sample)
    gold = read_jsonl(args.out)
    if not sample:
        logger.error("No sample at %s", args.sample)
        return 1
    client = SQLAlchemyClient()
    with client.get_session() as session:
        logger.info("database: %s", session.execute(text("SELECT current_database()")).scalar())
        current = current_categories(session, [r["sitemap_id"] for r in sample])
    missing = [r["sitemap_id"] for r in sample if r["sitemap_id"] not in current]
    if missing:
        logger.warning("%d sample rows no longer exist in sitemaps (category left as is): %s", len(missing), missing[:10])

    new_sample, new_gold, counts = refresh_rows(sample, gold, current)
    for k, v in counts.items():
        logger.info("  %-34s %6d", k, v)

    named = set(sources_with_named_branches())
    stale = [r for r in new_sample if r["source"] in named and (r.get("category") or "").startswith("http")]
    logger.info("  %-34s %6d  (sources with branch_name_from_url: %s)", "url_categories_left_on_named_sources", len(stale), ", ".join(sorted(named)))
    logger.info("  %-34s %6d", "duplicate_headline_groups_left", len(headline_groups(new_sample)))
    leaks = sum(1 for g in headline_groups(new_sample).values() if len({r["split"] for r in g}) > 1)
    logger.info("  %-34s %6d", "split_leak_groups_left", leaks)
    by_stratum = collections.Counter(r["stratum"] for r in new_sample)
    logger.info("strata after refresh: %s", ", ".join(f"{k}={v}" for k, v in sorted(by_stratum.items(), key=lambda kv: -kv[1])))

    if args.dry_run:
        logger.info("[dry-run] nothing written.")
        return 0
    write_jsonl(args.sample, new_sample)
    write_jsonl(args.out, new_gold)
    logger.info("Wrote %d sample rows to %s and %d gold rows to %s -- run `label` to fill the %d un-labelled row(s).",
                len(new_sample), args.sample, len(new_gold), args.out, len(new_sample) - len(new_gold))
    return 0


def cmd_merge_bodies(args) -> int:
    sample, gold, fetched = read_jsonl(args.sample), read_jsonl(args.out), read_jsonl(args.bodies)
    if not sample or not fetched:
        logger.error("need both %s and %s", args.sample, args.bodies)
        return 1
    new_sample, new_gold, counts = merge_bodies(sample, gold, fetched)
    for k, v in counts.items():
        logger.info("  %-44s %6d", k, v)
    logger.info("  %-44s %6d", "sample rows with a body now", sum(1 for r in new_sample if r["has_body"]))
    logger.info("  %-44s %6d", "sample rows still headline-only", sum(1 for r in new_sample if not r["has_body"]))
    if args.dry_run:
        logger.info("[dry-run] nothing written.")
        return 0
    write_jsonl(args.sample, new_sample)
    write_jsonl(args.out, new_gold)
    logger.info("Wrote %d sample rows and %d gold rows -- run `label` to re-label the %d row(s) that gained a body.",
                len(new_sample), len(new_gold), len(new_sample) - len(new_gold))
    return 0


def cmd_label(args) -> int:
    from newscrawler.core.constants import DAILY_API_CALL_LIMIT, GEMINI_MODEL, OPENAI_MODEL

    model_name = GEMINI_MODEL if args.provider == "gemini" else OPENAI_MODEL
    sample = read_jsonl(args.sample)
    if not sample:
        logger.error("No sample at %s -- run `sample` first", args.sample)
        return 1
    done = {r["sitemap_id"] for r in read_jsonl(args.out)}
    todo = [r for r in sample if r["sitemap_id"] not in done]
    # The sample file is sorted by sitemap_id (= by source, roughly). A
    # quota-limited day (the free tier is 20 calls/day/model, OPS-20) must
    # still cover every stratum and source, so batches are drawn in a seeded
    # shuffle of the remaining rows rather than in file order.
    random.Random(args.seed).shuffle(todo)
    batches = [todo[i:i + args.batch_size] for i in range(0, len(todo), args.batch_size)]
    logger.info("%d sample rows, %d already labelled, %d to label in %d call(s) of %d (provider %s, model %s)",
                len(sample), len(done), len(todo), len(batches), args.batch_size, args.provider, model_name)
    if not todo:
        logger.info("Nothing to label.")
        return 0

    if args.dry_run:
        prompt = build_label_prompt(batch_payload(batches[0]))
        logger.info("[dry-run] first prompt (%d chars):\n%s", len(prompt), prompt[:3000])
        logger.info("[dry-run] no API call made, nothing written.")
        return 0

    labeller, model_name = make_labeller(args.provider)

    if args.max_calls is not None:
        batches = batches[: args.max_calls]
    if labeller.budget_left() < len(batches):
        logger.warning("Daily API budget (%d) covers %d of %d call(s); the rest wait for a re-run.",
                       DAILY_API_CALL_LIMIT, labeller.budget_left(), len(batches))
        batches = batches[: max(0, labeller.budget_left())]

    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    write_lock = threading.Lock()
    stats = {"calls": 0, "labelled": 0, "rejected": 0, "failed": 0}

    def label_one(batch):
        prompt = build_label_prompt(batch_payload(batch))
        try:
            raw = labeller.call(prompt)
        except Exception as e:  # noqa: BLE001 -- resumable; this batch is retried on the next run
            logger.error("Gemini call failed: %r (batch of %d left for a re-run)", e, len(batch))
            with write_lock:
                stats["failed"] += 1
            return
        labels, problems = parse_labels(raw, batch)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        out_rows = []
        for r in batch:
            if r["sitemap_id"] not in labels:
                continue
            is_news, topic = labels[r["sitemap_id"]]
            out_rows.append({
                "sitemap_id": r["sitemap_id"], "source": r["source"], "category": r["category"],
                "headline": r["headline"], "body_head": r["body_head"], "has_body": r["has_body"],
                "had_body_at_freeze": r.get("had_body_at_freeze", r["has_body"]),
                "stratum": r["stratum"], "split": r["split"],
                "is_news": is_news, "topic": topic, "labeller": model_name, "labelled_at": now,
            })
        with write_lock:
            append_jsonl(args.out, out_rows)
            stats["calls"] += 1
            stats["labelled"] += len(out_rows)
            stats["rejected"] += len(batch) - len(out_rows)
            calls = stats["calls"]
        for p in problems[:5]:
            logger.warning("  call %d: %s", calls, p)
        if calls % 10 == 0:
            logger.info("%d call(s), %d labelled, %d left for a re-run", calls, stats["labelled"], stats["rejected"])

    # Calls are independent; --workers > 1 overlaps the model's latency
    # (~30-45 s per 20-row call with thinking on). The output file is
    # append-only under a lock, so a crash mid-run loses at most the batches
    # in flight, and the next run picks them up.
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futures = [ex.submit(label_one, b) for b in batches]
        for f in as_completed(futures):
            f.result()
    logger.info("Done: %d call(s), %d row(s) labelled, %d row(s) not accepted, %d call(s) failed "
                "(re-run to retry), output %s", stats["calls"], stats["labelled"], stats["rejected"],
                stats["failed"], args.out)
    return 0


def cmd_handcheck(args) -> int:
    gold = read_jsonl(args.gold)
    if not gold:
        logger.error("No gold rows at %s", args.gold)
        return 1
    rng = random.Random(args.seed)
    by_stratum: Dict[str, List[dict]] = collections.defaultdict(list)
    for r in gold:
        by_stratum[r["stratum"]].append(r)
    news_check: List[dict] = []
    strata = [s for s in STRATUM_ORDER if by_stratum.get(s)]
    per = max(1, args.n_news // max(1, len(strata)))
    for s in strata:
        pool = by_stratum[s][:]
        rng.shuffle(pool)
        news_check.extend(pool[:per])
    news_check = news_check[: args.n_news]
    chosen = {r["sitemap_id"] for r in news_check}
    by_topic: Dict[str, List[dict]] = collections.defaultdict(list)
    for r in gold:
        if r["is_news"] and r["sitemap_id"] not in chosen:
            by_topic[r["topic"]].append(r)
    topic_check: List[dict] = []
    topics = [t for t in TOPICS if by_topic.get(t)]
    per_t = max(1, args.n_topic // max(1, len(topics)))
    for t in topics:
        pool = by_topic[t][:]
        rng.shuffle(pool)
        topic_check.extend(pool[:per_t])
    topic_check = topic_check[: args.n_topic]

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["check", "sitemap_id", "stratum", "source", "category", "headline", "body_head_200",
                    "model_is_news", "model_topic", "human_is_news", "human_topic", "note"])
        for check, rows in (("is_news", news_check), ("topic", topic_check)):
            for r in rows:
                w.writerow([check, r["sitemap_id"], r["stratum"], r["source"], r["category"], r["headline"],
                            (r["body_head"] or "")[:200], r["is_news"], r["topic"], "", "", ""])
    logger.info("Wrote %d is_news rows + %d topic rows to %s -- fill human_is_news (true/false) and human_topic, "
                "then run score-handcheck", len(news_check), len(topic_check), args.out)
    return 0


def read_handcheck_csv(path: str) -> List[dict]:
    """The owner fills the CSV in Excel, which saves it back with a UTF-8 BOM,
    the locale's delimiter (`;` here) and TRUE/FALSE upper-cased. utf-8-sig
    eats the BOM; the delimiter is sniffed from the header line."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        header = f.readline()
        f.seek(0)
        delimiter = max((",", ";", "\t"), key=header.count)
        return list(csv.DictReader(f, delimiter=delimiter))


def cmd_score_handcheck(args) -> int:
    rows = read_handcheck_csv(args.csv)
    truthy = {"true": True, "false": False, "1": True, "0": False, "yes": True, "no": False, "y": True, "n": False}
    n_news = agree_news = n_topic = agree_topic = 0
    disagreements = []
    for r in rows:
        if r["check"] == "is_news":
            h = truthy.get((r.get("human_is_news") or "").strip().lower())
            if h is None:
                continue
            n_news += 1
            m = truthy[r["model_is_news"].strip().lower()]
            if h == m:
                agree_news += 1
            else:
                disagreements.append(("is_news", r["sitemap_id"], r["headline"], m, h))
        elif r["check"] == "topic":
            h = (r.get("human_topic") or "").strip()
            if not h:
                continue
            n_topic += 1
            if h == r["model_topic"].strip():
                agree_topic += 1
            else:
                disagreements.append(("topic", r["sitemap_id"], r["headline"], r["model_topic"], h))
    logger.info("is_news: %d checked, %d agree (%.1f%%); gate >= 95%%", n_news, agree_news,
                100 * agree_news / n_news if n_news else 0)
    logger.info("topic:   %d checked, %d agree (%.1f%%); gate >= 85%%", n_topic, agree_topic,
                100 * agree_topic / n_topic if n_topic else 0)
    for d in disagreements:
        logger.info("  %-7s %s %s  model=%s human=%s", *d)
    return 0


def cmd_stats(args) -> int:
    gold = read_jsonl(args.gold)
    logger.info("%d labelled rows in %s", len(gold), args.gold)
    if not gold:
        return 0

    def table(key, title):
        c = collections.Counter()
        n = collections.Counter()
        for r in gold:
            k = key(r)
            n[k] += 1
            c[k] += 1 if r["is_news"] else 0
        logger.info("%s:", title)
        for k, total in sorted(n.items(), key=lambda kv: -kv[1]):
            logger.info("  %-28s %5d rows  is_news %5.1f%%", str(k), total, 100 * c[k] / total)

    table(lambda r: r["stratum"], "per stratum")
    table(lambda r: r["source"], "per source")
    table(lambda r: r["split"], "per split")
    table(lambda r: "with body" if r["has_body"] else "headline only", "per has_body")
    tc = collections.Counter(r["topic"] for r in gold)
    logger.info("per topic:")
    for t in TOPICS:
        logger.info("  %-20s %5d%s", t, tc.get(t, 0), "  (< 100)" if 0 < tc.get(t, 0) < 100 else "")
    # SYS-43: the two invariants the fixture test pins, printed with the rest.
    by_key = collections.Counter((r["source"], normalise_headline(r["headline"])) for r in gold)
    same_source_dups = sum(n - 1 for n in by_key.values() if n > 1)
    train_keys = {normalise_headline(r["headline"]) for r in gold if r["split"] == "train"}
    leaks = sum(1 for r in gold if r["split"] == "test" and normalise_headline(r["headline"]) in train_keys)
    logger.info("same-source duplicate headline rows: %d; test rows whose headline is also in train: %d",
                same_source_dups, leaks)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("sample")
    p.add_argument("--size", type=int, default=4000)
    p.add_argument("--seed", type=int, default=20260920)
    p.add_argument("--out", default=SAMPLE_PATH)
    p.set_defaults(fn=cmd_sample)

    p = sub.add_parser("refresh")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--sample", default=SAMPLE_PATH)
    p.add_argument("--out", default=GOLD_PATH)
    p.set_defaults(fn=cmd_refresh)

    p = sub.add_parser("merge-bodies")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--bodies", default=os.path.join(FIXTURES, "filter_gold_bodies.jsonl"))
    p.add_argument("--sample", default=SAMPLE_PATH)
    p.add_argument("--out", default=GOLD_PATH)
    p.set_defaults(fn=cmd_merge_bodies)

    p = sub.add_parser("label")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--batch-size", type=int, default=20)
    p.add_argument("--max-calls", type=int, default=None)
    p.add_argument("--provider", choices=("gemini", "openai"), default="openai",
                   help="gemini: GEMINI_API_KEY/GEMINI_MODEL; openai: any OpenAI-compatible endpoint via "
                        "OPENAI_API_KEY/OPENAI_BASE_URL/OPENAI_MODEL (default; OPS-20)")
    p.add_argument("--workers", type=int, default=1, help="Concurrent labelling calls (default 1)")
    p.add_argument("--seed", type=int, default=20260920, help="Order in which the remaining rows are batched")
    p.add_argument("--sample", default=SAMPLE_PATH)
    p.add_argument("--out", default=GOLD_PATH)
    p.set_defaults(fn=cmd_label)

    p = sub.add_parser("handcheck")
    p.add_argument("--n-news", type=int, default=100)
    p.add_argument("--n-topic", type=int, default=50)
    p.add_argument("--seed", type=int, default=20260920)
    p.add_argument("--gold", default=GOLD_PATH)
    p.add_argument("--out", default=HANDCHECK_PATH)
    p.set_defaults(fn=cmd_handcheck)

    p = sub.add_parser("score-handcheck")
    p.add_argument("--csv", default=HANDCHECK_PATH)
    p.set_defaults(fn=cmd_score_handcheck)

    p = sub.add_parser("stats")
    p.add_argument("--gold", default=GOLD_PATH)
    p.set_defaults(fn=cmd_stats)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
