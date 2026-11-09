"""SYS-86 (#246): what the edition's echo guard hides on replayed days, for a verdict by hand.

Reads <dir>/<date>-stories.json (written by replay_newsletter_edition.py), rebuilds that day's
candidates and the editor's choice, and re-runs the guard of the code checked out now (so a rule
can be changed and re-measured without calling the LLM again). Prints:
  - HIDDEN: every Sekilas line the edition hides (newsletter_edition._sekilas), with the top
    story it repeats and the shared names / event words -- the lines the CTO's "<= 1 wrong hide"
    criterion is about;
  - with --all-pairs: every summarized candidate x top story pair the guard flags, and the pairs
    the first rule (before SYS-86) flagged, for comparison.

    venv\\Scripts\\python.exe scripts\\experiments\\probe_echo_guard.py --dates 2026-09-29 2026-09-30
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from newscrawler.core import newsletter_edition as ne  # noqa: E402
from newscrawler.core import story_words  # noqa: E402
from newscrawler.core.story_summary import StorySummary  # noqa: E402


def first_rule(candidate, top) -> bool:
    """The guard as built on 2026-10-05 (5fe7859/776e6e9), before SYS-86: >= 3 shared content
    words with a capitalised one among them, or >= 4; titles, months, units and money tokens counted."""
    import re
    stop = story_words.STOPWORDS - {"soal", "tentang", "terkait", "terhadap", "atas", "bahwa", "antara", "sejak",
                                    "per"}

    def words(text):
        out = {}
        for m in re.finditer(r"[^\W\d_][\w-]*", text):
            w, low = m.group(0), m.group(0).lower()
            if low in stop or (len(w) < 3 and not w.isupper()):
                continue
            before = text[:m.start()].rstrip()
            name = (w.isupper() and len(w) >= 2) or (w[0].isupper() and not (not before or before[-1] in ".!?"))
            out[low] = out.get(low, False) or name
        return out
    mine = words(f"{candidate.story.judul}. {candidate.story.sekilas}")
    theirs = words(f"{top.story.judul}. {top.story.inti}")
    shared = set(mine) & set(theirs)
    return len(shared) >= 4 or (len(shared) >= 3 and any(mine[w] or theirs[w] for w in shared))


def shared_words(candidate, top):
    mine = story_words.content_words(f"{candidate.story.judul}. {candidate.story.sekilas}")
    theirs = story_words.content_words(f"{top.story.judul}. {top.story.inti}")
    shared = set(mine) & set(theirs)
    names = sorted(w for w in shared if mine[w] and theirs[w])
    return names, sorted(shared - set(names))


def load(path):
    data = json.load(open(path, encoding="utf-8"))
    cands = []
    for c in data["candidates"]:
        s = c["story"]
        story = StorySummary(s["judul"], s["inti"], s["poin"], s["mengapa_penting"], s["sekilas"], s["terkait"],
                             s["tidak_terkait"]) if s else None
        cands.append(ne.Candidate(c["id"], c["topic"], {"story": story, "sources": ["x"] * c["portals"]},
                                  c["guaranteed"]))
    choice = ne.Choice(data["choice"]["utama"], [], [set(g) for g in data["choice"]["groups"]])
    return cands, choice


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dir", default=os.path.join(ROOT, "digests", "preview", "replay"))
    parser.add_argument("--dates", nargs="+", required=True)
    parser.add_argument("--all-pairs", action="store_true")
    args = parser.parse_args(argv)
    hidden_total = pairs_total = flagged_total = first_total = 0
    for day in args.dates:
        cands, choice = load(os.path.join(args.dir, f"{day}-stories.json"))
        by_id = {c.id: c for c in cands}
        tops = [by_id[i] for i in choice.utama]
        hidden = ne._sekilas(cands, choice)[1]
        hidden_total += len(hidden)
        print(f"\n### {day}: {len(tops)} top stories, {sum(c.summarized for c in cands)} summarized candidates, "
              f"{len(hidden)} Sekilas line(s) hidden")
        for cid in hidden:
            c = by_id[cid]
            for top in tops:
                if ne.echoes(c, top):
                    names, events = shared_words(c, top)
                    print(f"  HIDDEN  {c.story.sekilas}\n    TOP   {top.story.judul} -- {top.story.inti}\n"
                          f"          names {names}, events {events}")
        if not args.all_pairs:
            continue
        others = [c for c in cands if c.summarized and c.id not in choice.utama]
        for c in others:
            for top in tops:
                pairs_total += 1
                now, before = ne.echoes(c, top), first_rule(c, top)
                flagged_total += now
                first_total += before
                if now or before:
                    names, events = shared_words(c, top)
                    tag = "BOTH " if now and before else ("NOW  " if now else "FIRST")
                    print(f"  {tag} {c.story.judul}  ~  {top.story.judul}   names {names} events {events}")
    print(f"\nhidden lines: {hidden_total}" + (f"; pairs {pairs_total}: flagged now {flagged_total}, by the first "
                                              f"rule {first_total}" if args.all_pairs else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
