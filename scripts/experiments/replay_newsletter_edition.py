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

        def choose(*args, **kwargs):
            result = real_choose(*args, **kwargs)
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


_ENGLISH_MONTHS = re.compile(r"\b(January|February|March|May|June|July|August|October|December)\b")
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_PAGE_STARTS = ("Diberitakan", "Artikel terkait", "Sumber (", "Baca di")


def document_checks(markdown_paths, pdf_paths) -> dict:
    """SYS-81/SYS-84/OPS-41's Done-when on real files: what a reader sees has no
    English month, ISO date, source enum or telemetry; no PDF page starts with a
    source/link line or ends on a section heading."""
    from pypdf import PdfReader

    from newscrawler.core.newsletter_copy import OUTLET_NAMES, SECTION_NAMES
    found = {"english_month": [], "iso_date": [], "internal_source": [], "telemetry": [], "page_starts_with_meta": [],
             "page_ends_on_section": []}
    for path in markdown_paths:
        prose = re.sub(r"\]\([^)]*\)", "]", open(path, encoding="utf-8").read())   # URLs are not reader text
        found["english_month"] += _ENGLISH_MONTHS.findall(prose)
        found["iso_date"] += _ISO_DATE.findall(prose)
        no_brands = prose
        for brand in sorted(OUTLET_NAMES.values(), key=len, reverse=True):   # "CNN Indonesia" contains "CNN"
            no_brands = no_brands.replace(brand, " ")
        found["internal_source"] += [s for s in OUTLET_NAMES if re.search(rf"\b{s}\b", no_brands)]
        # ("WIB" is not on the list: articles say "pukul 05.55 WIB"; the old footer's time is caught by "Total artikel")
        found["telemetry"] += [t for t in ("Ringkasan AI", "Cluster", "deepseek", "Total artikel") if t in prose]
    sections = {n.upper() for n in SECTION_NAMES.values()} | set(SECTION_NAMES.values()) | {"BERITA UTAMA", "SEKILAS"}
    for pdf in pdf_paths:
        for number, page in enumerate(PdfReader(pdf).pages, 1):
            lines = [l.strip() for l in page.extract_text().splitlines()
                     if l.strip() and not l.strip().startswith("Rangkuman Berita ·")]
            if lines and lines[0].startswith(_PAGE_STARTS):
                found["page_starts_with_meta"].append(f"{os.path.basename(pdf)} p{number}: {lines[0][:60]}")
            if lines and lines[-1] in sections:
                found["page_ends_on_section"].append(f"{os.path.basename(pdf)} p{number}: {lines[-1]}")
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--date", required=True, help="YYYY-MM-DD, the articles' publication day")
    parser.add_argument("--old", help="an old digest of the same day, for the words-per-story comparison")
    parser.add_argument("--out-dir", default=os.path.join(ROOT, "digests", "preview", "replay"))
    parser.add_argument("--check-only", action="store_true",
                        help="no LLM, no DB: only the document checks on the files already in --out-dir")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.check_only:
        base = os.path.join(args.out_dir, args.date)
        mds = [p for p in (base + ".md", base + ne.EDITION_SUFFIX + ".md") if os.path.exists(p)]
        pdfs = [os.path.splitext(p)[0] + ".pdf" for p in mds if os.path.exists(os.path.splitext(p)[0] + ".pdf")]
        print("CHECKS " + json.dumps(document_checks(mds, pdfs), ensure_ascii=False))
        return 0

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
    pdfs = [render_digest_pdf(str(path))]
    pages["digest_a4"] = len(PdfReader(pdfs[0]).pages)
    if path.edition:
        pdfs.append(render_edition_pdf(path.edition))
        pages["edition_phone"] = len(PdfReader(pdfs[1]).pages)
        result["coverage"] = capture.coverage(e["sekilas"])
    result["pdf_pages"] = pages
    result["checks"] = document_checks([str(path)] + ([path.edition] if path.edition else []), pdfs)
    print("REPLAY " + json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
