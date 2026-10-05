"""Replay the newsletter (SYS-82/SYS-83/OPS-42) on a real day without writing to the database.

Runs the real generator with the configured summarizer over the day's articles,
exactly as `task=newsletter` does, but `save_digest` is a no-op (preview's
read-only datasource) and the files go to --out-dir (default
digests/preview/replay). Then it renders both PDFs and prints one JSON line of
the tickets' Done-when numbers:

    summaries   first-try share, share after the retry, refusals by reason
    words       average words per story, new digest vs an old digest of the same day
    edition     words, top stories, Sekilas lines, editor fallback and its reasons
    coverage    of the day's 6 largest stories by portal count, how many the edition shows
                (a top story, a Sekilas line, or a duplicate the editor folded into one)
    pdf_pages   the edition's phone PDF and the digest's A4 PDF

    venv\\Scripts\\python.exe scripts\\experiments\\replay_newsletter_edition.py --date 2026-10-04 ^
        --old digests\\2026-10-04.md

It reads Postgres and the MiniLM model, calls the LLM (~100 calls a day), and does
not touch FAISS or the DB's rows. EXPERIMENTS.md "2026-10-05 -- SYS-82/SYS-83 replay".
"""
import argparse
import json
import logging
import os
import re
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

import newscrawler.core.newsletter_edition as ne  # noqa: E402
import newscrawler.core.newsletter_generator as ng  # noqa: E402
from newscrawler.core.newsletter_pdf import render_digest_pdf, render_edition_pdf  # noqa: E402
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402
from preview_newsletter import ReadOnlyNewsletterDataSource  # noqa: E402

_META = ("**Sumber", "**Artikel terkait", "**Diberitakan")


def words_per_story(markdown: str) -> float:
    """Average words of a story's headline and summary (bullets, inti, poin,
    'Mengapa penting'); the source and link lines are not the story."""
    stories, current = [], None
    for line in markdown.splitlines():
        if line.startswith("### "):
            current = [line[4:]]
            stories.append(current)
        elif line.startswith(("## ", "# ", "---")):
            current = None
        elif current is not None and line.strip() and not line.startswith(_META) and not line.startswith("*…"):
            current.append(line.lstrip("- "))
    counts = [len(" ".join(s).split()) for s in stories]
    return round(sum(counts) / len(counts), 1) if counts else 0.0


class Capture:
    """What the edition was built from: the sections, the candidates and the editor's choice."""

    def __init__(self):
        self.sections = self.cands = self.choice = None
        real_candidates, real_choose = ne.candidates, ne.choose

        def candidates(sections):
            self.sections = sections
            self.cands = real_candidates(sections)
            return self.cands

        def choose(summarizer, cands, digest_date):
            result = real_choose(summarizer, cands, digest_date)
            self.choice = result[0]
            return result

        ne.candidates, ne.choose = candidates, choose

    def coverage(self, kept_sekilas: int) -> dict:
        """Of the 6 shown clusters with the most portals, how many the edition shows."""
        clusters = [c for s in self.sections for c in s["clusters"]]
        top6 = sorted(clusters, key=lambda c: -len(c["sources"]))[:6]
        id_of = {id(c.cluster): c.id for c in self.cands}
        shown = set(self.choice.utama)
        # the word budget drops Sekilas lines from the bottom, so the kept ones are the first
        shown |= {s.id for s in ne._sekilas(self.cands, self.choice)[:kept_sekilas]}
        for group in self.choice.groups:                      # a folded duplicate is shown through its twin
            if group & shown:
                shown |= group
        covered = [c for c in top6 if id_of.get(id(c)) in shown]
        return {"top6_portals": [len(c["sources"]) for c in top6], "covered": len(covered),
                "missed": [c.get("story").judul if c.get("story") else c["headline"]
                           for c in top6 if id_of.get(id(c)) not in shown]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--date", required=True, help="YYYY-MM-DD, the articles' publication day")
    parser.add_argument("--old", help="an old digest of the same day, for the words-per-story comparison")
    parser.add_argument("--out-dir", default=os.path.join(ROOT, "digests", "preview", "replay"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    os.makedirs(args.out_dir, exist_ok=True)
    ng.DIGESTS_DIR = args.out_dir
    stored = {}

    class Recording(ReadOnlyNewsletterDataSource):
        def save_digest(self, **kwargs):
            stored.update(kwargs)
            return 0

    capture = Capture()
    generator = ng.NewsletterGenerator(Recording(SQLAlchemyClient()))
    path = generator.generate(date.fromisoformat(args.date))
    categories = stored["categories"]
    s, e = categories[ng.SUMMARIES_KEY], categories[ng.EDITION_KEY]
    digest_md = open(path, encoding="utf-8").read()
    result = {
        "date": args.date, "digest": str(path), "edition": path.edition, "note": path.note,
        "summaries": {"total": s["total"], "summarized": s["summarized"], "first_try": s["first_try"],
                      "first_try_share": round(s["first_try"] / s["total"], 3) if s["total"] else None,
                      "after_retry_share": round(s["summarized"] / s["total"], 3) if s["total"] else None,
                      "rejections": s["rejections"], "stopped": s["stopped"]},
        "words_per_story": {"new": words_per_story(digest_md),
                            "old": words_per_story(open(args.old, encoding="utf-8").read()) if args.old else None},
        "edition_stats": e,
    }
    pages = {"digest_a4": None, "edition_phone": None}
    from pypdf import PdfReader
    pages["digest_a4"] = len(PdfReader(render_digest_pdf(str(path))).pages)
    if path.edition:
        pages["edition_phone"] = len(PdfReader(render_edition_pdf(path.edition)).pages)
        result["coverage"] = capture.coverage(e["sekilas"])
    result["pdf_pages"] = pages
    print("REPLAY " + json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
