"""SYS-103 (#273): which full-text query shape makes the keyword half of the search useful?

Read-only. For each question of the SYS-99 replay, it compares query shapes over the L2 chunks:
  and_all   plainto_tsquery: every word ANDed (today's query)
  or_all    the question's content words ORed
  names_and the names (acronyms, capitalised words, tickers, numbers) ANDed, plus at least one other word
  rare_or   the content words whose document frequency is under RARE_DF ORed, ranked by ts_rank_cd,
            at least min(2, n) of them present
and reports per shape: GIN matches (what has to be ranked), top-20 latency, and the top-5 headlines.
Each word's document frequency (share of L2 chunks containing it) is printed too.

    venv\\Scripts\\python.exe scripts\\experiments\\probe_fts_query_shapes.py [--rare-df 0.02]
"""
import argparse
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))
from sqlalchemy import text  # noqa: E402

from newscrawler.core.story_words import STOPWORDS  # noqa: E402
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

QUESTIONS = [
    "Kenapa rupiah melemah pekan ini?",
    "Bagaimana kinerja IHSG pekan ini?",
    "Apa kata OJK soal kredit perbankan?",
    "Apa isi RUU Ketenagakerjaan yang baru disahkan?",
    "Bagaimana harga minyak dunia terbaru?",
    "Apa perkembangan kasus korupsi yang ditangani KPK minggu ini?",
    "Di mana terjadi banjir atau longsor dalam sepekan terakhir?",
    "Apa keputusan Bank Indonesia soal BI-Rate?",
    "Bagaimana perkembangan konflik Iran terbaru?",
]
QUESTION_WORDS = frozenset("apa apakah bagaimana kenapa mengapa siapa kapan berapa mana dimana gimana "
                           "seperti adakah benarkah terbaru terkini sekarang kini sepekan terakhir".split())
TOKEN = re.compile(r"[\w][\w.,-]*\w|\w", re.UNICODE)


def terms(question):
    """(word, is_name) for the words worth searching: not a stop or question word."""
    out = []
    for m in TOKEN.finditer(question):
        word = m.group(0).strip(".,")
        low = word.lower()
        if low in STOPWORDS or low in QUESTION_WORDS or len(low) < 2:
            continue
        name = word.isupper() or any(c.isdigit() for c in word) or (m.start() > 0 and word[0].isupper())
        out.append((low, name))
    seen, unique = set(), []
    for low, name in out:
        if low not in seen:
            seen.add(low)
            unique.append((low, name))
    return unique


def lexeme(word):
    """A tsquery operand for a word as the 'simple' parser indexes it (BI-Rate -> bi-rate)."""
    return "'" + word.replace("'", "") + "'"


def run(session, tsquery, extra_where="", params=None):
    params = dict(params or {}, q=tsquery)
    t = time.monotonic()
    count = session.execute(text(f"SELECT COUNT(*) FROM chunks c WHERE c.chunk_level = 2 "
                                 f"AND c.fts_vector @@ to_tsquery('simple', :q) {extra_where}"), params).scalar()
    rows = session.execute(text(f"""
        SELECT s.headline, ts_rank_cd(c.fts_vector, to_tsquery('simple', :q)) AS r
        FROM chunks c JOIN sitemaps s ON s.sitemap_id = c.sitemap_id
        WHERE c.chunk_level = 2 AND c.fts_vector @@ to_tsquery('simple', :q) {extra_where}
        ORDER BY r DESC LIMIT 20"""), params).fetchall()
    ms = int((time.monotonic() - t) * 1000)
    heads, seen = [], set()
    for h, _ in rows:
        if h not in seen:
            seen.add(h)
            heads.append(h)
    return count, ms, heads[:5]


def idf_score(session, words, df, args):
    """The candidate set is the OR of the anchors: words under --anchor-df, names under --name-df,
    else the rarest word. Every word, the frequent ones included, adds its idf to the score when
    present, so 'harga minyak dunia' outranks 'minyak goreng'. At least min(2, anchors) anchors
    must be present, and a name when the question has one."""
    import math
    anchors = [w for w, n in words if df[w] < (args.name_df if n else args.anchor_df)]         or [min(words, key=lambda x: df[x[0]])[0]]
    names = [w for w, n in words if n and w in anchors]
    idf = {w: math.log(1 / max(df[w], 1e-6)) for w, _ in words}
    params = {f"t{i}": lexeme(w) for i, (w, _) in enumerate(words)}
    hit = {w: f"(c.fts_vector @@ to_tsquery('simple', :t{i}))::int" for i, (w, _) in enumerate(words)}
    score = " + ".join(f"{idf[w]:.4f} * {hit[w]}" for w, _ in words)
    need = min(2, len(anchors))
    where = f"AND ({' + '.join(hit[w] for w in anchors)}) >= {need}"
    if names:
        where += f" AND ({' + '.join(hit[w] for w in names)}) >= 1"
    params["q"] = " | ".join(lexeme(w) for w in anchors)
    t = time.monotonic()
    count = session.execute(text(f"SELECT COUNT(*) FROM chunks c WHERE c.chunk_level = 2 "
                                 f"AND c.fts_vector @@ to_tsquery('simple', :q) {where}"), params).scalar()
    tie = "s.posted_at DESC, " if args.order == "recency" else ""
    rows = session.execute(text(f"""
        SELECT s.headline, s.posted_at, ({score}) / {sum(idf.values()):.4f} AS coverage
        FROM chunks c JOIN sitemaps s ON s.sitemap_id = c.sitemap_id
        WHERE c.chunk_level = 2 AND c.fts_vector @@ to_tsquery('simple', :q) {where}
        ORDER BY coverage DESC, {tie}ts_rank_cd(c.fts_vector, to_tsquery('simple', :q)) DESC LIMIT 20"""),
                           params).fetchall()
    ms = int((time.monotonic() - t) * 1000)
    heads, seen = [], set()
    for h, posted, cov in rows:
        if h not in seen:
            seen.add(h)
            heads.append(f"{cov:.2f} {posted} {h}")
    return count, ms, heads[:5]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rare-df", type=float, default=0.02)
    ap.add_argument("--anchor-df", type=float, default=0.03)
    ap.add_argument("--name-df", type=float, default=0.10)
    ap.add_argument("--only", default="", help="comma-separated shapes to print (default: all)")
    ap.add_argument("--order", choices=("rank", "recency"), default="rank",
                    help="idf_score's tie-break among equal coverage: ts_rank_cd, or the newest first")
    args = ap.parse_args()
    client = SQLAlchemyClient()
    with client.get_session() as s:
        s.execute(text("SET statement_timeout = '30s'"))
        total = s.execute(text("SELECT COUNT(*) FROM chunks WHERE chunk_level = 2")).scalar()
        print(f"L2 chunks: {total}\n")
        for question in QUESTIONS:
            words = terms(question)
            df = {}
            for w, _ in words:
                df[w] = s.execute(text("SELECT COUNT(*) FROM chunks WHERE chunk_level = 2 AND "
                                       "fts_vector @@ to_tsquery('simple', :q)"), {"q": lexeme(w)}).scalar() / total
            print(f"## {question}")
            print("   terms: " + ", ".join(f"{w}{'*' if n else ''} {df[w]:.2%}" for w, n in words))
            shapes = {}
            t = time.monotonic()
            plain = s.execute(text("SELECT COUNT(*) FROM chunks c WHERE c.chunk_level = 2 AND "
                                   "c.fts_vector @@ plainto_tsquery('simple', :q)"), {"q": question}).scalar()
            shapes["and_all"] = (plain, int((time.monotonic() - t) * 1000), [])
            if words:
                shapes["or_all"] = run(s, " | ".join(lexeme(w) for w, _ in words))
                names = [w for w, n in words if n]
                others = [w for w, n in words if not n]
                if names:
                    q = " & ".join(lexeme(w) for w in names)
                    if others:
                        q += " & (" + " | ".join(lexeme(w) for w in others) + ")"
                    shapes["names_and"] = run(s, q)
                rare = [w for w, _ in words if df[w] < args.rare_df] or [min(words, key=lambda x: df[x[0]])[0]]
                need = min(2, len(rare))
                present = " + ".join(f"(c.fts_vector @@ to_tsquery('simple', :t{i}))::int" for i in range(len(rare)))
                shapes["rare_or"] = run(s, " | ".join(lexeme(w) for w in rare), f"AND ({present}) >= {need}",
                                        {f"t{i}": lexeme(w) for i, w in enumerate(rare)})
                shapes["idf_score"] = idf_score(s, words, df, args)
            for name, (count, ms, heads) in shapes.items():
                if args.only and name not in args.only.split(","):
                    continue
                print(f"   {name:<10} matches={count:<7} {ms:>5} ms")
                for h in heads:
                    print(f"        - {h[:100]}")
            print()


if __name__ == "__main__":
    main()
