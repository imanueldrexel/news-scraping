# LLM budget (owner decision 2026-10-12)

## Constraint
- **The project's LLM budget is about $100** (owner, 2026-10-12). It is prepaid on SumoPod (DeepSeek). That one balance pays for:
  - the nightly knowledge extraction;
  - the 12:00 newsletter;
  - the search answers (`web:`).
- When the balance is empty, all three degrade (429 `ExceededBudget`, then 401 "Key is blocked"). That is the balance, not a limit on the key.
- **Monetization is deferred:** "let's see where we could monetize it later". No paid feature work until the owner raises it.

## Spend so far (`api_usage_log`)
- ~$23.50 through 2026-10-10, nearly all extraction.
- Today's top-up ($22.50) pays for clearing the backlog on the nights of 10-12/13/14: ~$20.5, ~20k articles per night at ~$0.34 per 1,000.
- About **$56 of the $100** remains after 10-15.

## Decision: extract every article
- After the backlog clears, every new article is extracted, all topics. Owner's choice over "finance only" and "pause".
- **Nightly limit:**
  - `KNOWLEDGE_DAILY_COST_LIMIT_USD` stays at 8 until the backlog is clear;
  - **from 2026-10-15 it is 1.5**. Intake runs 1,800–3,900 articles/day, ~$0.60–1.35, so $1.5 covers a full day with headroom and stops a runaway night from emptying the shared balance.
- **Steady state:** ~$1.20/day, ~$36/month. The remaining ~$56 lasts about 1.5 months (to about the end of November).
- **The owner tops up "later".** With ~$2 left on the morning of 10-15, the balance covers about one more night. **A top-up is due by about 2026-10-16**, or the 10-17 newsletter fails.

## Levers if the budget gets tight (not chosen)
- A lower nightly limit (e.g. $0.60): extraction is finance-first, so the knowledge base stays current on finance topics.
- Pausing extraction: the newsletter and search cost cents a day.

## 2026-10-18 (evening): arcs stay on after the ADR-020 fixes
- **Owner decision 2026-10-18 (evening): keep `NEWSLETTER_ARCS=1`** for the 10-19 12:00 edition on the new gate code. Grounds: the new code is strictly stricter than what ran live 10-17/10-18 and fails closed to the plain story; the guards raised 0 exceptions on 6,231 real articles (EXPERIMENTS.md, fuzz_gate_on_corpus.py); SYS-152's measurement needs live sebab logs. QA keeps its sentence-by-sentence check; on the first false fact, set 0.
- Cost check: arc retries are cents (<= 8 calls/day); the day's spend is extraction at its $1.50 cap. Balance ~$4.
