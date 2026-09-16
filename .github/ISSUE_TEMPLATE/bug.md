---
name: Bug
about: Something in the pipeline, a scraper, or the tooling is wrong
title: ""
labels: bug
---

<!-- Add one severity label (P0 - critical / P1 - high / P2 - medium / P3 - low)
     and one area label (area: pipeline / observability / scraper / tech-debt). -->

- **Where:** `path/to/file.py:line`
- **Symptom:** what you observe (log line, wrong count, missing rows, health-check status)
- **Root cause:** why it happens — or "unknown yet" if not investigated
- **Evidence:** how it was confirmed (repro script, `check_crawlers.py` output, SQL result)
- **Fix:** proposed change
- **Done when:** the observable condition that lets this issue be closed (a test, a health-check line, a query result)
