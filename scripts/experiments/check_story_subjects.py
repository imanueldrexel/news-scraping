"""SYS-80 (#236): what the subject check did on replayed days, for a verdict by hand.

Reads <dir>/<date>-stories.json (written by replay_newsletter_edition.py) and prints:
  - per day: summary calls, accepted, fallbacks, refusals by reason;
  - every "subject" refusal: the story's judul, each article it flagged (outlet + headline), the
    anchors it was held to, and what the retry did (moved the article out / still refused);
  - every accepted story with a terkait article off its subject (story_summary.off_subject on the
    accepted answer: should be 0, since the retry moves such an article out);
  - how many articles the retries moved out (demoted).

    venv\\Scripts\\python.exe scripts\\experiments\\check_story_subjects.py --dates 2026-10-04 2026-09-29
"""
import argparse
import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from newscrawler.core.source_check import off_subject  # noqa: E402


def unanchored(story: dict, shown: list) -> list:
    return off_subject(story["judul"], story["inti"], {i: shown[i]["guard_text"] for i in story["terkait"]})[1]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dir", default=os.path.join(ROOT, "digests", "preview", "replay"))
    parser.add_argument("--dates", nargs="+", required=True)
    args = parser.parse_args(argv)
    total = collections.Counter()
    for day in args.dates:
        data = json.load(open(os.path.join(args.dir, f"{day}-stories.json"), encoding="utf-8"))
        calls = data["calls"]
        reasons = collections.Counter(r["reason"] for c in calls for r in c["refusals"])
        accepted = [c for c in calls if c["story"]]
        print(f"\n### {day}: {len(calls)} summary calls, {len(accepted)} accepted, "
              f"{len(calls) - len(accepted)} fell back; refusals {dict(reasons)}")
        total.update(calls=len(calls), accepted=len(accepted), **{f"refused_{k}": v for k, v in reasons.items()})
        for c in calls:
            subject = [r for r in c["refusals"] if r["reason"] == "subject"]
            if not subject:
                continue
            total["stories_with_subject_refusal"] += 1
            story = c["story"]
            outcome = (f"accepted: terkait {story['terkait']}, tidak_terkait {story['tidak_terkait']}, "
                       f"demoted {story.get('demoted', 0)}" if story
                       else f"FELL BACK after {[r['reason'] for r in c['refusals']]}")
            total["demoted"] += story.get("demoted", 0) if story else 0
            total["subject_accepted" if story else "subject_fell_back"] += 1
            print(f"  SUBJECT  {outcome}")
            if story:
                print(f"     judul: {story['judul']}")
            for r in subject:
                print(f"     refused: {r['detail'][:300]}")
            for i, a in enumerate(c["shown"]):
                print(f"     [{i}] {a['source']}: {a['headline'][:110]}")
        bad = [(c["story"]["judul"], [c["shown"][i]["headline"] for i in unanchored(c["story"], c["shown"])])
               for c in accepted if unanchored(c["story"], c["shown"])]
        total["accepted_unanchored"] += len(bad)
        for judul, heads in bad:
            print(f"  UNANCHORED (should not happen)  {judul}  <- {heads}")
    print(f"\nTOTAL {dict(total)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
