# ADR-019: The causal gate matches the claim to ONE link of the quote, cause to cause and effect to effect

**Status:** Accepted (owner, 2026-10-17: "Strict per half")
**Date:** 2026-10-17
**Feature:** newsletter-story-arcs (tracker #336); SYS-152 #342 send-back, SYS-181 #381, SYS-182 #382, SYS-183 #383,
SYS-184 #384, SYS-185 #385
**Author:** 10x-Team (Architect + Staff Engineer)
**Amends:** ADR-018, decision 2 ("the effect half and the cause half must EACH share >= 60% with that same kutipan").
Layers 1 (the `sebab` prompt field) and 3 (the shadow judge, SYS-180) are unchanged.

## Context
- ADR-018's gate measured both prose halves against the **whole** quote. QA's audit of SYS-152 (2026-10-17) showed
  that is still the MK failure, in five shapes:
  - **reversed** ("Harga avtur melonjak karena harga tiket naik", from "tiket naik karena avtur melonjak"); the
    ticket's own Done-when, "sehingga is checked with the halves swapped", was never built (SYS-152);
  - **two links in one quote**: the effect of one joined to the cause of the other, across two adjacent
    sentences or two clauses of one sentence (SYS-181);
  - **span**: the two-sentence cap counted on the quote as written, so "..." or dropped full stops let one
    "quote" cover a whole article (SYS-182);
  - **fronted cause** "Karena X, Y" read as "Akibatnya, Y": the effect Y never checked (SYS-183);
  - **negation**: "tidak naik karena" backed by "naik karena" (SYS-185).
- And the causal-word regex missed affixed forms and synonyms (mengakibatkan, dikarenakan, penyebabnya, pemicu,
  gara-gara, berimbas), so those needed no quote at all (SYS-184).

## Decision
1. **Every causal word has a direction.** One table (`causal_check._KINDS`) gives each form its kind:
   - *backward*, EFFECT w CAUSE: karena, dikarenakan, akibat, diakibatkan, lantaran, dipicu, disebabkan, sebab,
     imbas, gara-gara, penyebabnya, pemicunya;
   - *forward*, CAUSE w EFFECT: sehingga, menyebabkan, mengakibatkan, berakibat, memicu, berimbas, akibatnya,
     karenanya, imbasnya, penyebab, pemicu, and "karena / sebab / akibat itu".

   Where the side before the word is empty, the shape decides:
   - a *forward* word takes the previous sentence as the cause ("Akibatnya, Y", "Hal ini menyebabkan Y");
   - "penyebabnya / pemicunya" take the previous sentence as the effect ("Harga naik. Penyebabnya, X");
   - any other *backward* word is a **fronted cause** ("Karena X, Y"). The cause is the clause after it, and the
     effect is the rest of the sentence (SYS-183);
   - "Penyebab / Pemicu X adalah Y" splits at the copula.
2. **The prose and the source are cut the same way.** A claim is the (cause, effect) of one causal word of a
   prose sentence. A *link* is the (cause side, effect side) of one causal word of the source text that the quote
   covers. Each side stops at another causal word and at the sentence end. Source sides also stop at a
   contrastive or temporal conjunction (tetapi, namun, sementara, sedangkan, meski, padahal, setelah, sebelum,
   ketika, usai) and at ";". They do not stop at a comma: a source's cause is often a list.
3. **A claim is backed by one link: its effect is covered by that link's effect side and its cause by the link's
   cause side, each >= 60% (`MIN_HALF_OVERLAP`, the core clause too, as before).** The link's causal word must lie
   inside the quoted span (SYS-152 direction + SYS-181).
4. **The quote is a pointer into the source.** It is located in the source (normalised, "..." bridging in order).
   The sentences it covers are counted **in the source**, at most `MAX_QUOTE_SENTENCES` = 2. Their words are
   counted too, at most `MAX_QUOTE_WORDS` = 70. Links are cut from those source sentences, never from the model's
   wording, so a "..." cannot hide a "bukan" (SYS-182).
5. **Two sentences only through a back-reference.** A source side reaches into the previous covered sentence only
   when it holds fewer than 2 content words ("Hal ini", "Akibatnya,") or an anaphor ("... tersebut",
   "hal ini/itu"). That is ADR-018's "Hal ini menyebabkan" allowance, made exact: two unrelated sentences
   can no longer lend each other halves.
6. **Negation must agree (SYS-185).** A negator (tidak, tak, bukan, belum) negates the next content word, skipping
   modal and aspect words ("tidak dapat mendiskualifikasi", "tak kunjung terbit").
   - A word the claim negates must be negated in the matching side.
   - A negated word of the side that the claim uses must be negated in the claim.
   - A negator right before the causal word ("bukan karena") negates the link itself, and must match the link.
7. "berdampak", "terdampak", "terimbas" and "terpicu" stay out of the table. In the corpus they mean "affected"
   ("498 jiwa terdampak"), not a link between two stated facts (SYS-184).
8. The prompt lists the same classes as the table. A test pins the two together.

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
|---|---|---|---|
| Summed vote: words on the correct side must outnumber words on the crossed side, over both halves | keeps the dev's OMC fixture (5 vs 3) | a cause half taken wholly from the source's effect side passes, if the effect half is long enough: the MK shape again | owner chose strict per half |
| Halves against the whole quote (ADR-018 as built) | simplest | passes reversed, crossed, and spanned claims (QA's 25 red tests) | the failure this gate exists for |
| Fix each QA shape separately (swap halves only for sehingga; cap "..." length; special-case "Karena X,") | small diffs | five rules that do not share a model of "a link"; the next shape needs a sixth | one model of the link covers all five |
| An LLM judge as the gate | handles paraphrase | ADR-018's reasons stand (accuracy ~75%, worst on link errors) | stays a shadow (SYS-180) |

## Consequences
### Positive
- One idea, "a claim matches a link", covers SYS-152, 181, 182, 183 and 185. Each is a distinct line that a
  mutant can break.
- Sides come from the source text, so the model's wording of the quote no longer decides anything except where
  it points.

### Negative
- **OMC is refused** (owner decision). Its cause half "asap mengganggu operasi modifikasi cuaca" shares 1 of 5
  words with the source's cause side. "operasi modifikasi cuaca" is the source's *effect*, and the source never
  says the smoke disrupted the OMC. It joins Ojol as an accepted false refusal: the retry drops the "karena" and
  the reader gets the two facts side by side. The OMC Done-when line on SYS-181 is changed with this measurement.
- Stricter sides mean more retries on true paraphrased causes. The replay recheck reports backed/refused before
  and after.

### Risks
- An anaphor reaching across two covered sentences can still join two facts, when the second sentence truly
  refers back. That is the allowance's purpose.
- The direction table is hand-written. A causal form outside it bypasses the gate. The prompt lists the same
  forms, and the replay recheck counts what the wider regex finds.

## Dependencies
- `story_words.content_words` (stop words), and `causal_check._root` (rough affix stripping), unchanged.
- `story_arc.parse` wiring, unchanged: refusal reason `sebab`, one retry, fallback.

## Implementation notes (measured on the v4/v5/v6 replays, 2026-10-17, same day)
- **A name may stand anywhere in the link's sentence; the event words must be on their side** (`_covers`). Strict sides refused v4 Padang's "hujan deras memicu luapan air sungai di Koto Tangah": the source names Koto Tangah after its next causal word. OMC is unchanged: its missing words are event words. A half of names only gets no such room.
- Negators (checked by `negation_agrees`) and frame words ("lalu", "disebut", "sebelumnya") weigh nothing as facts.
- A source's headline and body are separate sentences (split at line breaks and at "ditebak.Dia" glue).
- Replay recheck: 15/18 backed before, 12/18 after. The 3 lost: OMC (owner decision), Dadang (the source gives the reason only as "Alasan ..." in a headline, accepted), and v4 Padang "karena banjir belum surut" (a true catch: the source says "dan").
