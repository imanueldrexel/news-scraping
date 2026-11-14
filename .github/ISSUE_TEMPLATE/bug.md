---
name: Bug
about: Something in the pipeline, a scraper, or the tooling is wrong
title: "[AREA-NN] "
labels: bug
---

<!-- One severity (P0 - critical / P1 - high / P2 - medium / P3 - low) + one area label.
     Keep the body under ~30 lines; design goes in an ADR. QA-filed bugs have no Fix line. -->

- **Where:** `path/to/file.py:line`
- **Symptom:** what you observe (log line, wrong count, missing rows, health-check status)
- **Root cause:** why it happens, or "unknown yet"
- **Evidence:** how it was confirmed (repro command and its output, SQL result)
- **Fix:** proposed change (dev's call)

## Acceptance criteria
<!-- 2-5 items. Kind: unit | integration | live: <command> | run: N | owner. Each "then" is observable. -->
- AC1 [unit]: Given ..., when ..., then ...
- AC2 [unit]: Given ..., when ..., then ...

## Verify
`venv\Scripts\python.exe -m pytest tests/unit/test_<id>_acceptance.py -q`

## Out of scope
- neighbouring cases this ticket deliberately does not cover
