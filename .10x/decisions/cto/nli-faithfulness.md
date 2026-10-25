# CTO: nli-faithfulness
- **Verdict:** build, in shadow. Owner wants NLI regardless of Indonesian accuracy; cost is local compute plus a few dollars of pair generation inside SYS-196's $5 cap.
- **Build vs buy:** no Indonesian targeted-error checker exists (research found none). Reuse a public multilingual XNLI checkpoint; build the eval set and harness ourselves.
- **Strategic value:** the eval set is the first Indonesian hedge-drop / invented-cause / end-date NLI measurement, a publishable result.
- **Reverses:** decision 7 of the gate-lexicon spec (ADR-024).
