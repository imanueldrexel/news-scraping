"""
Knowledge Base query CLI.

Usage:
    python -m newscrawler.tools.kb_query --entity "Bank Central Asia" --days 30
    python -m newscrawler.tools.kb_query --ticker BBCA --event-type earnings
    python -m newscrawler.tools.kb_query --entity "Perry Warjiyo" --from 2026-01-01
    python -m newscrawler.tools.kb_query --ticker BBCA --format json --output out.json
    python -m newscrawler.tools.kb_query --ticker BBCA --format csv --output out.csv
"""

import argparse
import csv
import json
import sys
from datetime import date, datetime
from io import StringIO
from typing import Optional

from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_knowledge_data_source import (
    SQLAlchemyKnowledgeDataSource,
)
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient


# ── Source authority for ranking display ────────────────────────────────────

SOURCE_AUTHORITY = {
    "BISNIS": 1.0, "KONTAN": 0.95, "INVESTORID": 0.90,
    "CNBC": 0.85, "IDXCHANNEL": 0.85, "KOMPAS": 0.80,
    "TEMPO": 0.75, "DETIK": 0.70, "ANTARA": 0.70,
}


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Query the NewsAggregator Knowledge Base",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--entity", type=str, help="Entity name to search for")
    group.add_argument("--ticker", type=str, help="IDX ticker symbol (e.g. BBCA)")

    parser.add_argument("--days",       type=int,  help="Number of past days to include")
    parser.add_argument("--from",       dest="from_date", type=str,
                        help="Start date YYYY-MM-DD")
    parser.add_argument("--to",         dest="to_date",   type=str,
                        help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--event-type", type=str,
                        help="Filter by event type (e.g. earnings, policy)")
    parser.add_argument("--format",     type=str,
                        choices=["table", "json", "csv"], default="table")
    parser.add_argument("--output",     type=str,
                        help="Output file path (default: stdout)")
    return parser.parse_args()


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


def _render_table(result: dict) -> str:
    entity   = result.get("entity") or {}
    mentions = result.get("mentions", [])
    co_occ   = result.get("co_occurrences", [])

    buf = StringIO()

    name   = entity.get("name", "Unknown")
    etype  = entity.get("entity_type", "")
    sub    = entity.get("subtype", "")
    ticker = entity.get("ticker", "")
    total  = result.get("total_mentions", 0)
    srcs   = result.get("source_count", 0)

    entity_line = f"Entity: {name}"
    if ticker:
        entity_line += f" ({ticker})"
    buf.write(entity_line + "\n")
    buf.write(f"Type: {etype}" + (f" / {sub}" if sub else "") + "\n")
    buf.write(f"Total mentions: {total} articles across {srcs} portals\n\n")

    if not mentions:
        buf.write("No mentions found for the given filters.\n")
    else:
        col_w = [12, 20, 60, 15, 40]
        header = (
            f"{'DATE':<{col_w[0]}}  {'SOURCE':<{col_w[1]}}  "
            f"{'HEADLINE':<{col_w[2]}}  {'EVENT':<{col_w[3]}}  CONTEXT"
        )
        buf.write(header + "\n")
        buf.write("-" * (sum(col_w) + 8) + "\n")
        for m in mentions:
            posted  = str(m.get("posted_at", ""))
            source  = (m.get("source") or "")[:col_w[1]]
            headline = (m.get("headline") or "")[:col_w[2]]
            event   = (m.get("event_type") or "")[:col_w[3]]
            ctx     = (m.get("context_snippet") or "")[:80].replace("\n", " ")
            buf.write(
                f"{posted:<{col_w[0]}}  {source:<{col_w[1]}}  "
                f"{headline:<{col_w[2]}}  {event:<{col_w[3]}}  {ctx}\n"
            )

    if co_occ:
        buf.write("\n── Co-occurring entities ──────────────────────────\n")
        persons = [c for c in co_occ if c["entity_type"] == "PERSON"]
        orgs    = [c for c in co_occ if c["entity_type"] == "ORGANIZATION"]
        locs    = [c for c in co_occ if c["entity_type"] == "LOCATION"]
        if persons:
            buf.write("People: " + ", ".join(
                f"{c['name']} ({c['count']}x)" for c in persons) + "\n")
        if orgs:
            buf.write("Organizations: " + ", ".join(
                f"{c['name']} ({c['count']}x)" for c in orgs) + "\n")
        if locs:
            buf.write("Locations: " + ", ".join(
                f"{c['name']} ({c['count']}x)" for c in locs) + "\n")

    return buf.getvalue()


def _render_json(result: dict) -> str:
    def _serialise(obj):
        if isinstance(obj, date):
            return obj.isoformat()
        raise TypeError(f"Not serialisable: {type(obj)}")
    return json.dumps(result, default=_serialise, ensure_ascii=False, indent=2)


def _render_csv(result: dict) -> str:
    mentions = result.get("mentions", [])
    buf = StringIO()
    if not mentions:
        return ""
    fieldnames = ["posted_at", "source", "headline", "link", "event_type", "context_snippet"]
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for m in mentions:
        row = {k: (str(v) if v is not None else "") for k, v in m.items()}
        writer.writerow(row)
    return buf.getvalue()


def main():
    # Windows consoles default to cp1252, which cannot encode the box-drawing characters
    # and Indonesian text in the output. Force UTF-8 so the tool works everywhere.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    args = _parse_args()

    from_date  = _parse_date(args.from_date)
    to_date    = _parse_date(args.to_date)

    client     = SQLAlchemyClient()
    datasource = SQLAlchemyKnowledgeDataSource(client)

    result = datasource.query_entity_mentions(
        entity_name=args.entity,
        ticker=args.ticker,
        days=args.days,
        from_date=from_date,
        to_date=to_date,
        event_type=args.event_type,
    )

    if result["entity"] is None:
        label = args.ticker or args.entity
        print(f"No entity found matching '{label}'.", file=sys.stderr)
        sys.exit(1)

    fmt = args.format
    if fmt == "table":
        output = _render_table(result)
    elif fmt == "json":
        output = _render_json(result)
    else:
        output = _render_csv(result)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Written to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
