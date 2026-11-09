# ADR-002: Cap a story's slots with one summarizer grouping call per section

**Status:** Accepted
**Date:** 2026-10-04
**Feature:** p1-p2-newsletter-fixes (SYS-67 #215)
**Author:** 10x-Team (Architect + Staff Engineer)

## Context
The 2026-09-28 digest showed one scandal (Lapas Cibinong) as five of a section's eight clusters, and one KPK cluster held two unrelated cases. The spec (`.10x/specs/2026-10-04-p1-p2-newsletter-fixes-design.md`) planned a measured sweep plus a headline-token merge pass. Measured on 2026-09-28/10-02/10-03:
- merging linked articles by the transitive closure of shared headline words produced one 176-article cluster (chaining);
- the same links as a distance bonus changed nothing;
- the scandal's own words are as frequent as "polisi", so no word-frequency cap finds the biggest story;
- cluster centroids of the scandal's angles are 0.23-0.45 apart, two unrelated KPK clusters 0.20 apart.

## Decision
`core/story_grouping.py`: once per section, before the summaries, ask the summarizer (ADR-001) which of the section's best 2x`NEWSLETTER_MAX_CLUSTERS_PER_TOPIC` clusters tell one story, and show at most `NEWSLETTER_MAX_CLUSTERS_PER_STORY` (2) of each; the rest join "and N more". A failed or unusable answer leaves the section as ranked and is counted in the footer and in `categories._summaries`. A quota error stops all calls. A cluster mixing two unrelated cases is not split; the summary prompt only says to summarize the event most articles are about.

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
|-------------|------|------|---------|
| Headline-token merge/split | No LLM, deterministic | Chains (176-article cluster); the biggest story's words look common | Measured failure |
| Distance bonus for linked headlines | No chaining | No measurable effect | Unproven complexity |
| Centroid-distance cap | Pure vectors | Cannot separate a scandal from two cases of one institution | Measured: 0.23-0.45 vs 0.20 |
| LLM flags mixed clusters and splits them | Would fix contamination | Returned `[]` for the known mixed cluster; per-cluster calls would double the cost | Not reliable enough |
| Do nothing | No cost | The visible repetition stays | Owner asked for P2 fixes |

## Consequences
### Positive
- A scandal can hold at most two slots; the other cases move up. 12 extra calls per digest, about 30 s.
- Failures are visible and never block the digest.

### Negative
- Curation now depends on an LLM answer; an outage or a bad answer degrades to the old ranking.
- Contamination (a cluster of two unrelated cases) is only softened in the summary, not fixed.

### Risks
- The model groups too aggressively (two real stories shown as one, one hidden): bounded by the cap of 2 and by "and N more"; QA reads `digests/preview/`.
- The prompt is Indonesian and tuned on one section; the parser accepts only a complete, valid grouping.

## Dependencies
- ADR-001's summarizer interface and quota handling.
- Constrains OPS-38 (a scheduled newsletter inherits the extra calls).
