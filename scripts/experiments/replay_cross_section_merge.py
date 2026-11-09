"""SYS-65 (#211): replay a day's section building offline (no LLM, no DB write) and
count shown-cluster pairs, in different sections, whose average member-to-member
cosine distance is at or under NEWSLETTER_CLUSTER_DISTANCE -- before the
cross-section merge (the merge stubbed out) and after.

    venv\Scripts\python.exe scripts\experiments\replay_cross_section_merge.py --date 2026-09-28
"""
import argparse
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

import numpy as np  # noqa: E402

import newscrawler.core.newsletter_generator as ng  # noqa: E402
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_newsletter_data_source import (  # noqa: E402,E501
    SQLAlchemyNewsletterDataSource,
)
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402


def close_pairs(sections, index_of, vectors):
    """[(topic_a, topic_b, distance)] for every pair of shown clusters in different sections at/under the cut."""
    shown = [(s["topic"], [index_of[a["sitemap_id"]] for a in c["articles"]]) for s in sections for c in s["clusters"]]
    unit = np.asarray(vectors, dtype=float)
    unit = unit / np.linalg.norm(unit, axis=1, keepdims=True)
    out = []
    for i, (ta, ia) in enumerate(shown):
        for tb, ib in shown[i + 1:]:
            d = 1.0 - float((unit[ia] @ unit[ib].T).mean())
            if ta != tb and d <= ng.NEWSLETTER_CLUSTER_DISTANCE:
                out.append((ta, tb, round(d, 3)))
    return len(shown), out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    args = ap.parse_args()
    d = date.fromisoformat(args.date)
    gen = ng.NewsletterGenerator(SQLAlchemyNewsletterDataSource(SQLAlchemyClient()), summarizer=None)
    articles = gen.ds.get_articles_for_date(int(d.strftime("%Y%m%d")))
    vectors = gen._encode([a['l1_text'] for a in articles])
    index_of = {a["sitemap_id"]: i for i, a in enumerate(articles)}
    print(f"{len(articles)} articles, threshold {ng.NEWSLETTER_CLUSTER_DISTANCE}")
    real_merge = gen._merge_across_sections
    for label, merge in (("before (merge off)", lambda entries, v: entries), ("after", real_merge)):
        gen._merge_across_sections = merge
        sections = gen.build_sections(articles, vectors)
        n, pairs = close_pairs(sections, index_of, vectors)
        print(f"{label}: {n} shown clusters, {len(sections)} sections, {len(pairs)} cross-section pairs at/under the cut {pairs}")


if __name__ == "__main__":
    main()
