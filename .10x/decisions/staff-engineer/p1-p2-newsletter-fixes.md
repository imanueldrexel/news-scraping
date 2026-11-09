# p1-p2-newsletter-fixes — staff engineer

### 2026-10-04 — Patterns
- Follow existing idioms: constants read in `core/constants.py` at import; tests with fakes under `tests/unit`; every guard gets a mutant in `scripts/experiments/qa_mutation_runner.py`; experiments logged in EXPERIMENTS.md.
- Counted-after-response rule for api_usage_log (OPS-09). Never log API keys.
- Cleaner patterns anchored at paragraph start; negative tests required.
- Reserved `_summaries` key in digest categories JSON; consumers skip `_` keys.
