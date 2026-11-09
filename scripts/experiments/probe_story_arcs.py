"""Does the corpus hold a usable back-story for a day's top stories? (newsletter story arcs, PM 2026-10-13)

For each lead article given (by link, as the edition prints it), looks back up to --days days
before its date along two routes and prints what each finds:

    entities   past articles sharing >= --min-shared of the lead's knowledge-base entities
               (entities mentioned in more than --max-df articles are skipped as generic:
               "Indonesia", "Pemerintah", ...)
    vectors    past articles whose NEWS_L1 vector (title + first two paragraphs) is within
               --min-cos cosine of the lead's

Per route: matched articles, distinct days, the span (first..last day), and the --show best
headlines with their date, so a person can judge whether they are the same thread.

Read-only: SELECTs on Postgres and a read of NEWS_L1 through index_generation.load_index
(no save). No LLM calls.

    venv\\Scripts\\python.exe scripts\\experiments\\probe_story_arcs.py --edition digests\\2026-10-12-ringkas.md
"""
import argparse
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.core.constants import EMBEDDING_MODEL_HF, VECTOR_DB_NAME_L1  # noqa: E402
from newscrawler.core.utils.hf_cache import resolve_model  # noqa: E402
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402


def lead_links(edition_path: str) -> list:
    """The Berita Utama headline links of an edition, in order."""
    out = []
    for line in open(edition_path, encoding="utf-8"):
        m = re.match(r"### \[(.+?)\]\((\S+?)\)", line)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def ymd(d: date) -> int:
    return int(d.strftime("%Y%m%d"))


def as_date(v) -> date:
    return datetime.strptime(str(int(v)), "%Y%m%d").date()


def find_lead(conn, link: str):
    bare = link.split("?page=all")[0]
    row = conn.execute(text(
        "SELECT a.articles_id, a.sitemap_id, s.headline, s.posted_at, s.sources "
        "FROM sitemaps s JOIN articles a ON a.sitemap_id = s.sitemap_id "
        "WHERE s.link IN (:a, :b) LIMIT 1"), {"a": bare, "b": link}).fetchone()
    return row


def entity_route(conn, article_id, day: date, days: int, min_shared: int, max_df: int):
    ents = conn.execute(text(
        "SELECT DISTINCT e.entity_id, e.name, e.entity_type, e.mention_count FROM entity_mentions m "
        "JOIN entities e ON e.entity_id = m.entity_id WHERE m.article_id = :a"), {"a": article_id}).fetchall()
    kept = [e for e in ents if e.mention_count <= max_df]
    if not kept:
        return ents, kept, []
    rows = conn.execute(text(
        "SELECT m.article_id, m.posted_at, count(DISTINCT m.entity_id) AS shared, "
        "array_agg(DISTINCT e.name) AS names, min(s.headline) AS headline, min(m.source) AS source "
        "FROM entity_mentions m JOIN entities e ON e.entity_id = m.entity_id "
        "JOIN articles a ON a.articles_id = m.article_id JOIN sitemaps s ON s.sitemap_id = a.sitemap_id "
        "WHERE m.entity_id = ANY(:ids) AND m.posted_at >= :lo AND m.posted_at < :hi "
        "GROUP BY m.article_id, m.posted_at HAVING count(DISTINCT m.entity_id) >= :k "
        "ORDER BY shared DESC, m.posted_at DESC"),
        {"ids": [e.entity_id for e in kept], "lo": day - timedelta(days=days), "hi": day,
         "k": min_shared}).fetchall()
    return ents, kept, rows


def lead_l1_text(conn, sitemap_id):
    r = conn.execute(text("SELECT text_content FROM chunks WHERE sitemap_id = :s AND chunk_level = 1 LIMIT 1"),
                     {"s": sitemap_id}).fetchone()
    return r[0] if r else None


def vector_route(vs, query: str, sitemap_id, day: date, days: int, min_cos: float, k: int):
    lo, hi = ymd(day - timedelta(days=days)), ymd(day)
    hits = vs.similarity_search_with_score(query, k=k)
    out, seen = [], set()
    for doc, dist in hits:
        md = doc.metadata
        cos = 1 - dist / 2   # squared L2 on normalised vectors (SYS-110)
        try:
            p = int(str(md.get("posted_at"))[:8])
        except (TypeError, ValueError):
            continue
        sid = md.get("sitemap_id")
        if sid == sitemap_id or sid in seen or not (lo <= p < hi) or cos < min_cos:
            continue
        seen.add(sid)
        out.append((cos, p, sid, md.get("headline") or doc.page_content[:90]))
    return out


def summarize(label, rows_by_day, show_rows):
    days = sorted(rows_by_day)
    span = f"{as_date(days[0])}..{as_date(days[-1])}" if days else "-"
    n = sum(len(v) for v in rows_by_day.values())
    print(f"  {label}: {n} articles over {len(days)} days, span {span}")
    for r in show_rows:
        print("     ", r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--edition", required=True)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--min-shared", type=int, default=2)
    ap.add_argument("--max-df", type=int, default=3000)
    ap.add_argument("--min-cos", type=float, default=0.75)
    ap.add_argument("--k", type=int, default=400)
    ap.add_argument("--show", type=int, default=8)
    ap.add_argument("--no-vectors", action="store_true")
    a = ap.parse_args()

    vs = None
    if not a.no_vectors:
        from langchain_community.embeddings import HuggingFaceEmbeddings
        from newscrawler.infrastructure.datasource.dataflow.write.faiss.index_generation import load_index
        emb = HuggingFaceEmbeddings(model_name=resolve_model(EMBEDDING_MODEL_HF),
                                    encode_kwargs={"normalize_embeddings": True})
        vs = load_index(os.path.join(ROOT, VECTOR_DB_NAME_L1), emb)

    from sqlalchemy import create_engine
    engine = create_engine(SQLAlchemyClient().database_uri)
    with engine.connect() as conn:
        for title, link in lead_links(a.edition):
            print("=" * 100)
            print(title)
            lead = find_lead(conn, link)
            if lead is None:
                print("  lead article not found:", link)
                continue
            day = as_date(lead.posted_at)
            print(f"  lead {lead.sources} {day} sitemap_id={lead.sitemap_id}")

            ents, kept, rows = entity_route(conn, lead.articles_id, day, a.days, a.min_shared, a.max_df)
            print(f"  entities: {len(ents)} on the lead, {len(kept)} specific "
                  f"(skipped: {', '.join(e.name for e in ents if e.mention_count > a.max_df) or '-'})")
            print(f"    specific: {', '.join(e.name for e in kept)}")
            by_day = defaultdict(list)
            for r in rows:
                by_day[ymd(r.posted_at)].append(r)
            summarize("entity route", by_day,
                      [f"{r.posted_at} [{r.shared}] {r.source}: {r.headline[:80]}  ({', '.join(r.names[:4])})"
                       for r in rows[:a.show]])

            if vs is not None:
                q = lead_l1_text(conn, lead.sitemap_id)
                if q:
                    hits = vector_route(vs, q, lead.sitemap_id, day, a.days, a.min_cos, a.k)
                    vday = defaultdict(list)
                    for h in hits:
                        vday[h[1]].append(h)
                    summarize(f"vector route (cos>={a.min_cos})", vday,
                              [f"{h[1]} {h[0]:.3f}: {str(h[3])[:90]}" for h in hits[:a.show]])


if __name__ == "__main__":
    main()
