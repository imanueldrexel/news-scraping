"""QA (SYS-86 #246): how often does newsletter_edition.echoes fire on real story pairs (top story x
every other story of the same day's full digest)? Candidate text: judul + the first 15 words of its
inti (sekilas proxy, so it over-states overlap). Prints every flagged pair for a by-hand verdict.

    venv\\Scripts\\python.exe scripts\\experiments\\qa_newsletter_244\\probe_echo_real.py
"""
import os
import re
import sys
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, REPO)
from newscrawler.core import newsletter_edition as ne
from newscrawler.core.story_summary import StorySummary

ROOT = os.path.join(REPO, "digests", "preview", "replay")


def stories(path):
    out, cur, section = [], None, None
    for line in open(path, encoding="utf-8").read().splitlines():
        if line.startswith("## "):
            section = line[3:]
        elif line.startswith("### "):
            cur = {"judul": re.sub(r"^\[(.*)\]\(.*\)$", r"\1", line[4:]), "inti": None, "section": section}
            out.append(cur)
        elif cur is not None and cur["inti"] is None and line.strip() and not line.startswith(("- ", "**")):
            cur["inti"] = line.strip()
    return [s for s in out if s["inti"]]


def cand(cid, s, sekilas=None):
    st = StorySummary(s["judul"], s["inti"], [], "", sekilas or " ".join(s["inti"].split()[:15]), [0], [])
    return ne.Candidate(cid, "x", {"story": st, "sources": [], "links": []})


total_flag = total_pairs = 0
for d in ("2026-09-28", "2026-10-03", "2026-10-04"):
    full = stories(f"{ROOT}/{d}.md")
    tops = [s for s in stories(f"{ROOT}/{d}-ringkas.md") if s["section"] == "Berita Utama"]
    top_titles = {t["judul"] for t in tops}
    top_full = [s for s in full if s["judul"] in top_titles]
    others = [s for s in full if s["judul"] not in top_titles]
    print(f"\n### {d}: {len(top_full)}/{len(tops)} tops matched, {len(others)} other stories")
    for t in top_full:
        for o in others:
            total_pairs += 1
            if ne.echoes(cand(2, o), cand(1, t)):
                total_flag += 1
                mine = ne.content_words(f"{o['judul']}. {' '.join(o['inti'].split()[:15])}")
                theirs = ne.content_words(f"{t['judul']}. {t['inti']}")
                print(f"  TOP  {t['judul']}\n  HIDE {o['judul']}  [{o['section']}]\n       shared={sorted(set(mine) & set(theirs))}")
print(f"\nflagged {total_flag} of {total_pairs} pairs")
