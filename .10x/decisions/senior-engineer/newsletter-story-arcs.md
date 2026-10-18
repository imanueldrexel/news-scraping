
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

## 2026-10-18: implementation approach for QA's 10-18 queue (ADR-020)
- `story_words.root(word)`: -nya, then the prefix list. A ke-/pe(r/n/m/ng)- prefix with an -an suffix also strips
  the -an, when >= 4 letters remain. `causal_check._root = story_words.root`, so the old call sites stay.
- `_covers(half, side, link)`: the link, not its sentence, so the opposite side is known. Every event root must be on
  `side`. Every name root on `side`, or in `link.sentence` minus the opposite side's roots. A half of names only
  follows the same rule.
- Span gains `hedged: bool`. `negated` also takes a denial frame. Both are computed from the link's region of the
  sentence (between the neighbouring causal runs). `supports` adds `not link.hedged or claim.hedged`.
- `_cut`: a purpose word right before membuat/mendorong/menekan makes it no causal word. `causal_spans` and
  `links` skip such matches through one helper (`_causal_matches`), so prose and source agree.
- Anaphor: `_lends_previous(before, previous)`, one predicate replacing the two `if` arms.
- Fronted, source side: cut at the last boundary. Prose away-side: `_items(text)`, the comma items up to a
  conjunction boundary. `_covered` runs per item.
- source_check: `_END_GAP` gains the "pada" tail and the degree words. `_END_OPEN` (hingga|sampai (dengan)|s.d.|s/d|
  berakhir/selesai/dicabut (pada)) is shared by `_END_POINT` and `_STATED_END`. The part key carries its unit. Ends
  are paired with their sentence's roots for SYS-193.
- story_arc: `_cued(text, start)` becomes a clause scan. SYS-190 is wired next to `unstated_future_times`, by field.
