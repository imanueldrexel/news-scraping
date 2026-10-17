
## 2026-10-17: SYS-152 implementation plan (ADR-018)
- **New module `core/causal_check.py`.** Pure functions only, so it is tested without the arc. It holds the causal-word table, `causal_spans(text)` (each causal word with its effect and cause clauses), `quote_in(quote, source)` (normalised substring: lower-case, every non-word character removed, "..." bridges pieces in order, at most 2 sentences), `overlap(half, quote)` (content words via `story_words`, -nya and verb prefixes stripped, roots matched by tail >= 4 chars), and `unbacked_causes(fields, entries, sources) -> [problem]`.
- **Clause halves.**
  - The clause is cut at `,;:` and at the conjunctions dan/tetapi/namun/sementara/meski.
  - Before: the last clause; widened one clause while it has fewer than 2 content words. After: the first clause, widened the same way.
  - An attribution segment ("menurut X", ", kata X") is removed before counting.
  - A causal word with no content words before it ("Akibatnya, ...", "Karena itu ...") takes the previous sentence as its other half.
  - Both halves are compared with the same quote, so the connective's direction does not matter.
- **`story_arc`.**
  - The `sebab` field is first in the JSON example and the prompt rule is rewritten. `_sebab()` parses it: a missing field is `[]`; a bad shape is `json`. A quote may only point at a terkait article or a chosen alur item.
  - New reason `"sebab"` in REASONS, ordered after date and before subject. It is checked on the lenient retry too (fail closed).
- **Tests.**
  - `tests/unit/test_causal_check.py` (pure) on QA's six real sentences with the real source text from `scripts/experiments/sys152/dump_causal_fixtures.py`.
  - `test_story_arc.py` end to end.
  - Registry mutants `sys152_*`.
