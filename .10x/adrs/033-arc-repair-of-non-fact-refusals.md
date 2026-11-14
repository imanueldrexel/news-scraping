# ADR-033: A refused arc is repaired, without a model call, only for refusals that are not about facts

**Status:** Accepted (owner, 2026-11-10)
**Date:** 2026-11-10
**Feature:** newsletter-story-arcs
**Author:** 10x-Team (Architect + Staff Engineer)

## Context
SYS-148's arcs fall back to the plain summary after two refused answers. On SYS-150's replay (2026-10-08..10-12, run on 334ecdc) 13 of 20 arcs were accepted (65%); the live editions accepted 23 of 36 (64%).

The 20 final refusals split into:
- **non-fact (13):** length 6, style 5, json 2;
- **fact (7):** sebab 4, date 2, number 1.

The owner's aim is that no fact is ever falsely claimed (2026-11-10). A fallback costs story quality, not truth. Loosening a fact check to reach SYS-148's 90% target would break that aim, and even repairing every non-fact refusal tops out at ~85-89%.

## Decision
1. **`story_arc.repair`.** When `write_arc` ends with no arc, each refused answer whose refusal is repairable is repaired, last answer first. Repairable means length, style, or a json refusal that names an index problem. The repaired answer is then checked by `parse(..., lenient=True)`, the same checks as the retry. The first repaired answer that passes is the arc. Otherwise it falls back, as today.
2. **The repairs only remove.**
   - **length:** drop whole trailing sentences of `hari_ini`, `latar` or `agenda` until each fits `LIMITS`. An `agenda` that one sentence cannot fit is dropped whole: it is optional, and is already dropped for other reasons. `judul` and `sekilas` are never edited, so a long one stays refused.
   - **style:** drop trailing sentences of `latar` while `chronicle` objects. At least one sentence is kept.
   - **json, index problems:** drop indexes out of range and duplicate indexes. An article in both `terkait` and `tidak_terkait` loses its `terkait` place. An article in neither goes to `tidak_terkait`. A `terkait` left empty is not repaired. Unparseable JSON is not repaired.
3. **Never drop a sentence that may qualify what came before**: one with a negation (`causal_check._NEGATORS`), a hedge (`causal_check._HEDGE`) or a contrast word (namun, tetapi, tapi, meski, meskipun, walau, walaupun, padahal, sementara). Only trailing sentences are dropped, so no reference ("Angka itu ...") can lose its antecedent. Nothing inside a sentence is cut.
4. **No fact check changes:** number, date, sebab, subject and alur. Every one of them runs on the repaired answer.
5. **Measured:** `StoryArc.repaired` names the repaired reason, and the edition's arc stats count `repaired`.

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
|---|---|---|---|
| Loosen style / sebab / date to reach 90% | meets the old target | raises the chance of a false fact | contradicts the owner's aim |
| A third model call ("shorten this") | may fix more | money; a new answer can carry new facts, so the checks see new text | not deterministic; the owner chose no extra call |
| Trim inside a sentence (cut clauses) | fixes one-sentence overruns | can drop a qualifier mid-sentence and change meaning | fact risk; whole sentences only |
| Accept 65% and do nothing | zero work | a third of top stories lose their story for non-fact reasons | owner chose to repair |

## Consequences
### Positive
- Acceptance rises with no new fact risk: every accepted arc has passed every check.
- No extra model cost, and the result is deterministic and replayable from stored answers.

### Negative
- A repaired arc is shorter than the model wrote: its later turning points or agenda are gone.
- A one-sentence overrun, or a long `judul` / `sekilas`, still falls back.

### Risks
- A dropped trailing sentence carried context the reader needed. Mitigation: never drop a negation, hedge or contrast sentence; the style rules still hold; the owner reads the replay.
- A repair loop that never ends. Mitigation: each step removes a sentence or an index, so it is bounded by the answer's length.

## Dependencies
- SYS-148 (ADR-016/017), `llm_json.ask_json` (its `answers` / `refusals`), ADR-031 (fact lists frozen).
- It supersedes SYS-148's ">= 90% accepted" Done-when (owner, 2026-11-10).
