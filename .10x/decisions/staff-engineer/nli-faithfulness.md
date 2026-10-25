# Staff Engineer: nli-faithfulness
- Follows existing patterns: migration registered in `scripts/migrate.py` and applied to both DBs (DBT-22); reader strings stay out of this (no reader text); revision recorded like SYS-61's encoder.json.
- Model loading lazy, like the web singletons; no import-time cost in `constants.py`.
- Mutants for every guard (copy-based runner; never git stash).
- Experiments logged in `EXPERIMENTS.md` the same session (CLAUDE.md rule).
