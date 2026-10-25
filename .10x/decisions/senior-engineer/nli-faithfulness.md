# Senior Engineer: nli-faithfulness approach
- Hook: `write_arcs` returns `(arcs, stats, trace)`; the shadow step runs on `arcs` + `trace` after the edition file is written. `shown = pick_articles(cluster["articles"])`; `arc.terkait` indexes it; quotes = `guard_text(a)` for terkait + `item_source(t)` for `arc.alur_items` (exactly what the lexicon gate reads).
- Sentences: reuse `causal_check.sentences`. Fields: judul, hari_ini, latar, agenda, sekilas.
- Premise chunks: split each source with `causal_check.sentences`, pair sentence-level; verdict = best p_entail.
- v1 DEVIATION from spec 4.1: the hypothesis is the WHOLE sentence; the sentence and the quotes' ids are stored, so SYS-199 re-scores minimal propositions offline without re-running editions. error_tag in v1 = which existing gate regex families the sentence matches (cheap `causal_check._causal_matches`, `_HEDGE`, `_DENIAL`, `source_check` end/future phrases), else NULL = residual.
- Scorer is injected (protocol) so tests and the replay tool never load a model.
- Edition output unchanged: shadow reads only; any exception -> WARNING, rows skipped.
- No import-time model load; `NLI_SHADOW`, `NLI_MODEL`, `NLI_TIME_BUDGET_S` read in `constants.py` like other settings.
