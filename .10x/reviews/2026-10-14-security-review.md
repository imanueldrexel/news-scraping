# Security review 2026-10-14: SYS-154..160 (story-arc style, time and ordinal guards)

**Scope:**
- `core/arc_style.py` (new);
- `source_check.relative_times / relative_name / ordinal_claims`;
- `story_arc.chronicle / unbacked_times / overcounted`;
- `replay_story_arcs.py` (`--compare`, `--metrics-from`).

**Verdict:** no security finding.

- **Input:** the new code reads model output and article text only, the same trust level as the SYS-148 guards. It writes nothing to the DB and makes no network call. The replay script's `--metrics-from DIR` reads local files the operator names.
- **Regex cost:** the patterns run on short fields (≤ 70 words) and on the story's source texts.
  - The patterns are alternations of fixed words with bounded `\s+`. There are no nested quantifiers over the same characters.
  - `_ORDINAL`'s optional `before` word is `[^\W\d_][\w-]*\s+`, which is linear.
  - The 84 QA tests and the dev's 227 run in < 3 s.
- **Prompt injection:** article text reaches the arc prompt, as before (SYS-148). The guards are what limit a manipulated answer: numbers, dates, relative times and claims are held to the sources. SYS-162 (#357) narrows "stated in a source" to today's articles, a small tightening of that boundary.
- **Secrets:** none touched. The read-only DB checks in this audit used `.env` credentials in-process and printed no secret.
