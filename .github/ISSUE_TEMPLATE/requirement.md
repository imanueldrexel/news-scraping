---
name: Requirement / improvement
about: A new capability, or a better way to do something that already exists
title: "[AREA-NN] "
labels: enhancement
---

<!-- One area label. One behaviour per ticket; keep the body under ~30 lines; design goes in an ADR. -->

- **Motivation:** the problem or gap, and who benefits (2-4 lines)
- **Proposal:** what to build or change (files, tables, scripts, config)

## Acceptance criteria
<!-- 2-5 items. Kind: unit | integration | live: <command> | run: N | owner. Each "then" is observable. -->
- AC1 [unit]: Given ..., when ..., then ...
- AC2 [unit]: Given ..., when ..., then ...

## Verify
`venv\Scripts\python.exe -m pytest tests/unit/test_<id>_acceptance.py -q`

## Out of scope
- neighbouring cases this ticket deliberately does not cover
