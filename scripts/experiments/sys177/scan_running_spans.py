"""SYS-177 second send-back (#407): which stored edition sentences hold a relative time span still running on their
edition's date, and would a "past word" rule refuse them?

For every digests/**/*.md named by a date, each sentence's `relative_times_at` phrase whose span ends on or after that
date (and is no future phrase) is printed with two flags: cued = `story_arc._cued` (the plan-verb cue, what the latar
check reads today) and past = a past word (sebelumnya, lalu, sempat, sejak, telah, sudah, pernah, mulai, kemarin,
tadi) before the phrase or up to 12 characters after it. A latar sentence with cued=0 and past=0 is what QA's
proposal ("a running latar span is a schedule unless a past word stands by it") would start refusing.

Read-only, no DB, no model call.

    venv\\Scripts\\python.exe scripts\\experiments\\sys177\\scan_running_spans.py
"""
import glob
import os
import re
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

from newscrawler.core import source_check as sc  # noqa: E402
from newscrawler.core import story_arc as sa  # noqa: E402

PAST = re.compile(r"\b(?:sebelumnya|lalu|sempat|sejak|telah|sudah|pernah|mulai|kemarin|tadi)\b", re.IGNORECASE)


def main():
    seen = set()
    for path in sorted(glob.glob(os.path.join(ROOT, "digests", "**", "*.md"), recursive=True)):
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", os.path.basename(path))
        if not m:
            continue
        day = date(*map(int, m.groups()))
        for line in open(path, encoding="utf-8").read().splitlines():
            for s in re.split(r"(?<=[.!?])\s+", line):
                for start, phrase, first, last in sc.relative_times_at(s, day):
                    if last < day or sc.future_phrases(phrase) or (s.strip(), day) in seen:
                        continue
                    seen.add((s.strip(), day))
                    cued = sa._cued(s, start, start + len(phrase))
                    past = bool(PAST.search(s[:start + len(phrase) + 12]))
                    print(f"{day} cued={int(cued)} past={int(past)} [{phrase}] {s.strip()[:170]}  "
                          f"<{os.path.relpath(path, ROOT)}>")


if __name__ == "__main__":
    main()
