"""SYS-67 (#215): does the story-grouping call put every angle of one incident in one story?

The unit tests fake the summarizer, so they cannot say whether the real model groups
the way `pick_shown` needs. This probe does, on real clusters, against the live
summarizer (a few calls, a fraction of a cent each):

  save   Build one day's sections (read-only Postgres + the MiniLM model, ~3 min) and
         write the ranked pool of one section as a fixture: per cluster its first
         headlines. Hand-annotate `expect` in the file (indexes that must share a
         story, indexes that must not).
  check  Read a fixture, ask the model for the grouping N times, print every answer,
         and fail (exit 1) when an expectation is violated or the answers differ.

    venv\\Scripts\\python.exe scripts\\experiments\\probe_story_grouping.py save --date 2026-09-28 --topic law_crime
    venv\\Scripts\\python.exe scripts\\experiments\\probe_story_grouping.py check tests\\fixtures\\story_grouping_2026-09-28_law_crime.json --runs 3

`expect` is {"together": [[indexes that are one incident]], "apart": [[a, b], ...]}.
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures")


def cmd_save(args):
    from datetime import date
    import newscrawler.core.newsletter_generator as ng
    from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_newsletter_data_source import (
        SQLAlchemyNewsletterDataSource,
    )
    from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient
    gen = ng.NewsletterGenerator(SQLAlchemyNewsletterDataSource(SQLAlchemyClient()), summarizer=None)
    day = date.fromisoformat(args.date)
    articles = gen.ds.get_articles_for_date(int(day.strftime("%Y%m%d")))
    sections = gen.build_sections(articles, gen._encode([a["l1_text"] for a in articles]))
    section = next(s for s in sections if s["topic"] == args.topic)
    pool = section["ranked"][: 2 * ng.NEWSLETTER_MAX_CLUSTERS_PER_TOPIC]
    out = {"date": args.date, "topic": args.topic, "expect": {"together": [], "apart": []},
           "clusters": [{"headlines": [a["headline"] for a in c["articles"][:6]], "portals": len(c["sources"])}
                        for c in pool]}
    path = os.path.join(FIXTURE_DIR, f"story_grouping_{args.date}_{args.topic}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for i, c in enumerate(out["clusters"]):
        print(i, c["headlines"][0][:100])
    print("->", path)
    return 0


def cmd_check(args):
    from newscrawler.core.story_grouping import group_clusters
    from newscrawler.core.summarizer import build_summarizer
    import newscrawler.core.newsletter_generator as ng
    fixture = json.load(open(args.fixture, encoding="utf-8"))
    if args.prompt_file:                       # try a prompt without editing the code
        import newscrawler.core.story_grouping as story_grouping
        story_grouping._PROMPT = open(args.prompt_file, encoding="utf-8").read()
    clusters = [{"articles": [{"headline": h} for h in c["headlines"]]} for c in fixture["clusters"]]
    summarizer = build_summarizer()
    if summarizer is None:
        print("no summarizer configured (OPENAI_API_KEY / GEMINI_API_KEY)", file=sys.stderr)
        return 2
    answers = []
    for run in range(args.runs):
        groups = group_clusters(summarizer, clusters)
        answers.append(sorted(sorted(g) for g in groups))
        print(f"run {run}: {answers[-1]}")
    ok = True
    if any(a != answers[0] for a in answers):
        print("UNSTABLE: the answers differ between runs")
        ok = False
    group_of = {i: n for n, g in enumerate(answers[-1]) for i in g}
    for together in fixture["expect"]["together"]:
        if len({group_of[i] for i in together}) != 1:
            print(f"FAIL together {together}: split across {sorted({group_of[i] for i in together})}")
            ok = False
    for a, b in fixture["expect"]["apart"]:
        if group_of[a] == group_of[b]:
            print(f"FAIL apart ({a}, {b}): grouped")
            ok = False
    shown = ng.pick_shown(clusters, answers[-1], ng.NEWSLETTER_MAX_CLUSTERS_PER_STORY,
                          ng.NEWSLETTER_MAX_CLUSTERS_PER_TOPIC)
    for together in fixture["expect"]["together"]:
        slots = sum(1 for c in shown if clusters.index(c) in together)
        print(f"slots taken by {together[:4]}...: {slots} of {len(shown)} (cap {ng.NEWSLETTER_MAX_CLUSTERS_PER_STORY})")
        if slots > ng.NEWSLETTER_MAX_CLUSTERS_PER_STORY:
            ok = False
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("save")
    s.add_argument("--date", required=True)
    s.add_argument("--topic", required=True)
    s.set_defaults(fn=cmd_save)
    c = sub.add_parser("check")
    c.add_argument("fixture")
    c.add_argument("--runs", type=int, default=3)
    c.add_argument("--prompt-file", default=None, help="a replacement for story_grouping._PROMPT ({{clusters}} placeholder)")
    c.set_defaults(fn=cmd_check)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
