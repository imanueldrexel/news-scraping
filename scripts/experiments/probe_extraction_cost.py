#!/usr/bin/env python3
"""
OPS-20 (#136) / SYS-39 (#125) step 1: what does one knowledge-extraction call
cost, per configuration, on real articles?

Sends the extractor's own prompt (`knowledge_extractor._PROMPT_TEMPLATE`,
article text cut at 3,000 chars exactly as `_call_gemini` does) for the same
N recent articles to each configuration, and records the provider's token
counts (input, output, thinking), latency, whether the answer parses as the
schema, and how many entities it names. The first configuration is the
reference; the others report entity overlap (Jaccard on normalised names) with it.

Configurations:
  flash        gemini-2.5-flash, as production calls it (thinking on by default)
  flash-nothink gemini-2.5-flash, thinking_budget=0
  flash-again  gemini-2.5-flash as production calls it, a second time: the
               reference's agreement with itself, the noise floor for "jacc"
  lite         --lite-model (default gemini-3.5-flash-lite; 2.5-flash-lite is
               closed to new users, 404 on 2026-09-29), thinking left at default
  deepseek     OPENAI_MODEL at OPENAI_BASE_URL (SumoPod deepseek-v4-flash), thinking disabled

Every call is counted in api_usage_log under its model name, like the pipeline's
calls (the Gemini free tier on this project is 20 requests/day/model, OPS-20).
Writes nothing else. No article row is marked extracted.

Usage:
    venv\\Scripts\\python.exe scripts/experiments/probe_extraction_cost.py --n 6
    venv\\Scripts\\python.exe scripts/experiments/probe_extraction_cost.py --n 6 --configs flash-nothink,deepseek

First run + conclusions: EXPERIMENTS.md, 2026-09-29 "OPS-20 / SYS-39: extraction cost per article, measured".
"""
import argparse
import json
import os
import sys
import time

from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
load_dotenv(os.path.join(ROOT, ".env"))

from sqlalchemy import text  # noqa: E402

from newscrawler.core.knowledge_extractor import _PROMPT_TEMPLATE  # noqa: E402
from newscrawler.infrastructure.datasource.dataflow.write.sqlalchemy.sql_alchemy_knowledge_data_source import (  # noqa: E402
    SQLAlchemyKnowledgeDataSource,
)
from newscrawler.infrastructure.network.clients.sqlalchemy_client import SQLAlchemyClient  # noqa: E402

CONFIGS = ("flash", "flash-again", "flash-nothink", "lite", "deepseek")


def sample_articles(n):
    """The newest n saved articles with a real body, one per topic first."""
    with SQLAlchemyClient().get_session() as s:
        rows = s.execute(text("""
            SELECT DISTINCT ON (a.topic) a.articles_id, a.topic, a.extracted_text
            FROM articles a WHERE length(a.extracted_text) > 800 AND a.topic IS NOT NULL
            ORDER BY a.topic, a.articles_id DESC""")).fetchall()
    return rows[:n]


def call_gemini(client, model, prompt, thinking_budget=None):
    config = {"response_mime_type": "application/json"}
    if thinking_budget is not None:
        config["thinking_config"] = {"thinking_budget": thinking_budget}
    t = time.monotonic()
    r = client.models.generate_content(model=model, contents=prompt, config=config)
    u = r.usage_metadata
    return (r.text, time.monotonic() - t, getattr(u, "prompt_token_count", 0) or 0,
            getattr(u, "candidates_token_count", 0) or 0, getattr(u, "thoughts_token_count", 0) or 0)


def call_openai(client, model, prompt):
    t = time.monotonic()
    r = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}, extra_body={"thinking": {"type": "disabled"}})
    u = r.usage
    reasoning = getattr(getattr(u, "completion_tokens_details", None), "reasoning_tokens", 0) or 0
    return (r.choices[0].message.content, time.monotonic() - t, u.prompt_tokens, u.completion_tokens - reasoning,
            reasoning)


def entities(raw):
    try:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].removeprefix("json")
        d = json.loads(raw)
    except Exception:  # noqa: BLE001
        return None
    names = set()
    for key in ("persons", "organizations", "locations"):
        for e in d.get(key) or []:
            if isinstance(e, dict) and isinstance(e.get("name"), str):
                names.add((key, " ".join(e["name"].lower().split())))
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--configs", default=",".join(CONFIGS))
    ap.add_argument("--lite-model", default="gemini-3.5-flash-lite")
    ap.add_argument("--json", help="also write the raw per-call rows here")
    args = ap.parse_args()
    configs = args.configs.split(",")
    ds = SQLAlchemyKnowledgeDataSource(SQLAlchemyClient())
    from google import genai
    gclient = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    oclient = None
    if "deepseek" in configs:
        from openai import OpenAI
        oclient = OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url=os.environ["OPENAI_BASE_URL"])

    articles = sample_articles(args.n)
    print(f"{len(articles)} articles, topics: {[a.topic for a in articles]}")
    rows, ref = [], {}
    for cfg in configs:
        for a in articles:
            prompt = _PROMPT_TEMPLATE.format(article_text=a.extracted_text[:3000])
            try:
                if cfg in ("flash", "flash-again"):
                    model, out = "gemini-2.5-flash", call_gemini(gclient, "gemini-2.5-flash", prompt)
                elif cfg == "flash-nothink":
                    model, out = "gemini-2.5-flash", call_gemini(gclient, "gemini-2.5-flash", prompt, 0)
                elif cfg == "lite":
                    model, out = args.lite_model, call_gemini(gclient, args.lite_model, prompt)
                else:
                    model = os.environ["OPENAI_MODEL"]
                    out = call_openai(oclient, model, prompt)
            except Exception as e:  # noqa: BLE001
                print(f"  {cfg} article {a.articles_id}: {type(e).__name__}: {str(e)[:160]}")
                continue
            ds.increment_api_call_count(model)
            raw, secs, tin, tout, tthink = out
            ents = entities(raw or "")
            if cfg == configs[0] and ents is not None:
                ref[a.articles_id] = ents
            base = ref.get(a.articles_id)
            overlap = (len(ents & base) / len(ents | base)) if ents is not None and base else None
            rows.append({"config": cfg, "article": a.articles_id, "in": tin, "out": tout, "think": tthink,
                         "secs": round(secs, 2), "parsed": ents is not None, "entities": len(ents or ()),
                         "overlap_vs_ref": overlap})
    print(f"\n{'config':14} {'n':>2} {'in':>6} {'out':>5} {'think':>6} {'secs':>5} {'parsed':>6} {'ents':>5} {'jacc':>5}")
    for cfg in configs:
        r = [x for x in rows if x["config"] == cfg]
        if not r:
            print(f"{cfg:14}  0")
            continue
        n = len(r)
        ov = [x["overlap_vs_ref"] for x in r if x["overlap_vs_ref"] is not None]
        print(f"{cfg:14} {n:2} {sum(x['in'] for x in r)/n:6.0f} {sum(x['out'] for x in r)/n:5.0f} "
              f"{sum(x['think'] for x in r)/n:6.0f} {sum(x['secs'] for x in r)/n:5.1f} "
              f"{sum(x['parsed'] for x in r):3}/{n:<2} {sum(x['entities'] for x in r)/n:5.1f} "
              f"{(sum(ov)/len(ov)) if ov else float('nan'):5.2f}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=1)


if __name__ == "__main__":
    main()
