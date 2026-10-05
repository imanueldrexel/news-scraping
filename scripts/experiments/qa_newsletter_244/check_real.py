"""QA (tracker #244): check the three replayed editions (real LLM output) against the tickets'
limits, and their PDFs (no page starting on a link line or ending on a section heading).

    venv\\Scripts\\python.exe scripts\\experiments\\qa_newsletter_244\\check_real.py
"""
import os
import re
import sys
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
from datetime import date
from pypdf import PdfReader
import newscrawler.core.newsletter_edition as ne
import newscrawler.core.newsletter_copy as copy
import run_scheduled_newsletter as rsn

ROOT = os.path.join(REPO, "digests", "preview", "replay")
W = lambda s: len(s.split())

for d in ("2026-09-28", "2026-10-03", "2026-10-04"):
    md = open(f"{ROOT}/{d}-ringkas.md", encoding="utf-8").read()
    issues = []
    sixty = md.split("## Hari Ini dalam 60 Detik")[1].split("## Berita Utama")[0]
    s60 = re.findall(r"^- (.*)$", sixty, re.MULTILINE)
    if not 3 <= len(s60) <= 5: issues.append(f"60s count {len(s60)}")
    issues += [f"60s {W(s)}w: {s}" for s in s60 if W(s) > 18]
    top = md.split("## Berita Utama")[1].split("## Sekilas")[0]
    stories = top.split("\n### ")[1:]
    if not 6 <= len(stories) <= 8: issues.append(f"utama {len(stories)}")
    for s in stories:
        lines = [l for l in s.splitlines() if l.strip()]
        judul = re.match(r"\[(.*?)\]", lines[0]).group(1)
        inti = lines[1]
        poin = [l[2:] for l in lines if l.startswith("- ")]
        why = [l for l in lines if l.startswith("**Mengapa")]
        if W(judul) > 12: issues.append(f"judul {W(judul)}w: {judul}")
        if W(judul) > 10: issues.append(f"(judul over the asked 10: {W(judul)}w) {judul}")
        if W(inti) > 25: issues.append(f"inti {W(inti)}w: {inti}")
        if len(poin) > 2: issues.append("poin>2")
        issues += [f"poin {W(p)}w: {p}" for p in poin if W(p) > 20]
        issues += [f"why {W(x) - 2}w" for x in why if W(x) - 2 > 20]
        if s.count("Baca di") != 1: issues.append("baca di count")
    sek = re.findall(r"^- \*\*(.*?) ·\*\* (.*)$", md.split("## Sekilas")[1], re.MULTILINE)
    issues += [f"sekilas {W(t)}w: {t}" for _, t in sek if W(t) > 15]
    per = {}
    for sec, _ in sek:
        per[sec] = per.get(sec, 0) + 1
    over = {k: v for k, v in per.items() if v > 3}
    if over: issues.append(f"sekilas >3/section {over}")
    words = ne.reader_words(md)
    sentences, ntop = ne.briefing(md)
    msg = rsn.edition_message(date.fromisoformat(d), sentences, ntop)
    print(f"== {d}: words={words} (split {len(md.split())}) utama={len(stories)} sekilas={len(sek)} msg={len(msg)} chars")
    for i in issues:
        print("   ", i)
    for kind, pdf in (("phone", f"{ROOT}/{d}-ringkas.pdf"), ("a4", f"{ROOT}/{d}.pdf")):
        r = PdfReader(pdf)
        bad = []
        for n, page in enumerate(r.pages, 1):
            lines = [l for l in page.extract_text().splitlines() if l.strip() and "Rangkuman Berita ·" not in l]
            if not lines:
                bad.append(f"p{n} empty"); continue
            if lines[0].startswith(("Baca di", "Artikel terkait", "Diberitakan", "·")) or re.match(r"^[a-z]", lines[0]):
                bad.append(f"p{n} starts: {lines[0][:60]!r}")
            last = lines[-1].strip()
            if last.upper() == last and len(last) < 40 and re.search(r"[A-Z]", last):
                bad.append(f"p{n} ends: {last!r}")
        print(f"   {kind}: {len(r.pages)} pages {bad}")
