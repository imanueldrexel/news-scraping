#!/usr/bin/env python3
"""
SRC-35 (#128) / SRC-39 (#133): decide a branch from its titles, never from its
name. For each (source, branch) given, print N real headlines -- from the
`sitemaps` table when we already crawled that branch, otherwise by fetching the
branch's own sitemap through the crawler's page loader (read-only, nothing
saved).

    python scripts/experiments/sample_branch_titles.py --website VIVA --branches bola,otomotif
    python scripts/experiments/sample_branch_titles.py --ambiguous          # the SRC-35 shortlist
    python scripts/experiments/sample_branch_titles.py --website DETIK --all-kept

--all-kept (SRC-50 #162) samples EVERY branch the source would crawl today: the
live index is fetched once and passed through the shipped `drop_soft_branches`
predicates, so the list is what a real run lists. It exists because a sweep that
searches for vocabulary words cannot find a soft leaf that contains none (DETIK
kept `f1`, `raket`, `relationship` = horoscopes). The only complete check is
reading every kept leaf's titles.
"""
import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.core.crawler_dict_list import CRAWLER_DICT  # noqa: E402

# The leaves whose name does not settle them (SRC-35: `teknologi` is news,
# `transportasi` is business, `otomotif` was business on WARTAEKONOMI).
AMBIGUOUS = {
    "BERITASATU": ["ototekno", "sport", "lifestyle"],
    "CNBC": ["lifestyle", "entrepreneur", "syariah", "tech"],
    "CNN": ["teknologi", "otomotif", "edukasi", "gaya-hidup", "hiburan"],
    "DETIK": ["gadget", "fotostop_news", "konsultasigadget", "games-news"],
    "IDXCHANNEL": ["video", "foto", "idxtainment", "ecotainment"],
    "JPNN": ["teknologi", "otomotif", "ramadan", "travel", "english", "lifestyle"],
    "KONTAN": ["kesehatan", "sehat", "lifestyle", "english", "filmon"],
    "KUMPARAN": ["tekno-sains", "otomotif", "food-travel"],
    "OKEZONE": ["women", "muslim", "ototekno"],
    "SINDONEWS": ["tekno", "otomotif", "kalam", "lifestyle"],
    "TRIBUN": ["kesehatan", "musik", "seleb"],
    "TVONENEWS": ["religi", "lifestyle"],
    "VIVA": ["otomotif", "digital", "english", "gaya-hidup"],
    "WARTAEKONOMI": ["otomotif", "kesehatan", "transportasi", "travel", "english_edition", "entertainment_life_style"],
    "PIKIRANRAKYAT": ["KlikSeleb", "Sportaliga"],
}


def from_db(session, source, branch, n):
    rows = session.execute(
        text("SELECT headline FROM sitemaps WHERE sources = :s AND lower(category) = lower(:c) "
             "ORDER BY posted_at DESC, sitemap_id DESC LIMIT :n"),
        {"s": source, "c": branch, "n": n},
    ).fetchall()
    return [r.headline for r in rows]


def live_branches(crawler):
    return crawler.list_branches() or {}  # every index (SRC-38)


def from_live(crawler, branch, n, branches=None):
    try:
        if branches is None:
            branches = live_branches(crawler)
            if not branches:
                return ["(no index)"]
        link = branches.get(branch)
        if not link:
            return [f"(branch {branch!r} not in the live index: {sorted(branches)[:6]}...)"]
        leaf = crawler.page_loader.get_soup(link)
        if not leaf:
            return ["(branch sitemap did not fetch)"]
        out = []
        for url in leaf.find_all("url")[:n]:
            title = crawler._get_title(url)
            if not title:
                loc = url.find("loc")
                title = crawler._derive_headline_from_url(loc.get_text(" ").strip()) if loc else None
            out.append(title or "(no title)")
        return out or ["(empty sitemap)"]
    except Exception as e:  # noqa: BLE001
        return [f"(error: {type(e).__name__}: {e})"[:120]]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--website")
    parser.add_argument("--branches", help="Comma-separated branch keys")
    parser.add_argument("--ambiguous", action="store_true", help="The SRC-35 shortlist above")
    parser.add_argument("--all-kept", action="store_true",
                        help="Every branch --website would crawl today (live index, shipped drop predicates)")
    parser.add_argument("-n", type=int, default=3)
    args = parser.parse_args(argv)

    index = {}
    if args.all_kept:
        source = args.website.upper()
        crawler = CRAWLER_DICT[source]
        listed = live_branches(crawler)
        index[source] = listed
        kept = sorted(crawler.drop_soft_branches(listed))
        print(f"{source}: {len(listed)} listed, {len(kept)} kept")
        targets = {source: kept}
    elif args.ambiguous:
        targets = dict(AMBIGUOUS)
    else:
        targets = {args.website.upper(): [b.strip() for b in args.branches.split(",")]}
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    client = SQLAlchemyClient()

    jobs = []
    with client.get_session() as session:
        for source, branches in targets.items():
            for branch in branches:
                titles = from_db(session, source, branch, args.n)
                jobs.append((source, branch, titles))
    # anything with no stored rows gets one live fetch
    todo = [(i, s, b) for i, (s, b, t) in enumerate(jobs) if not t]
    if todo:
        with ThreadPoolExecutor(max_workers=6) as ex:
            live = list(ex.map(lambda x: from_live(CRAWLER_DICT[x[1]], x[2], args.n, index.get(x[1])), todo))
        for (i, _, _), titles in zip(todo, live):
            jobs[i] = (jobs[i][0], jobs[i][1], [f"[live] {t}" for t in titles])

    for source, branch, titles in jobs:
        print(f"\n=== {source} / {branch}")
        for t in titles:
            print(f"    {(t or '')[:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
