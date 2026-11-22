# ADR-032: Two word classes are read from how the archive writes its words

**Status:** Proposed (dev, 2026-11-07; QA to verify, owner may overrule)
**Date:** 2026-11-07
**Feature:** rag-search-redesign (follow-ups) / newsletter-story-arcs (causal gate)
**Author:** 10x-Team (SDE)

## Context
Two regressions of the 11-06 audit came from a rule that needed to know what *kind* of word stands in a place and had only a hand list to ask:
- #448/#449: `followup._opening_subject` took any capitalised opening word before a -nya word as the follow-up's own subject ("Sritex ujung-ujungnya bangkrut?"). A time word, a particle or a hedge ("Kemarin / Kok / Benarkah / Kira-kira harganya ...?") is not in its short exclusion list, so a thread follow-up was searched alone.
- #440: `causal_check._cause_follows` took any content word after "tertekan / terkerek / terseret ..." as a cause. A word of the movement itself ("tertekan tajam", "tertekan sepanjang perdagangan", "terkerek naik") made a plain market sentence a causal claim, and a true paraphrase was refused.

Three QA rounds showed that a hand list fails on the first held-out word (ADR-031). Both questions have an answer in the archive, 202,635 articles, measured 2026-11-07:
- A name is written capitalised where no sentence starts; a common word in lower case. Mid-sentence uses, lower/capitalised: kemarin 1469/7, kok 321/12, kira-kira 216/0, masa 6964/202; Sritex 0/10, Antam 22/1768, Garuda 11/407.
- A word of the movement follows a market-movement verb ("melemah tajam", "menguat tipis") far more often than a noun-taking cause marker ("akibat aksi jual", "dipicu kekhawatiran"). Per 60k articles, after movement / after cause: tajam 481/0, tipis 291/0, sepanjang 45/2, signifikan 222/72; aksi 30/225, kenaikan 4/288, sentimen 0/140.

## Decision
1. `scripts/build_word_classes.py` (read-only) builds two committed files from the archive:
   - `newscrawler/web/common_words.txt`: words written in lower case where no sentence starts, in >= 5 uses and >= half of them.
   - `newscrawler/core/movement_words.txt`: common words that follow an unambiguous movement verb >= 5 times and >= 3x the per-use rate after a cause marker; no numerals.
2. `_opening_subject`: an opening word is the follow-up's own subject only when it is no common word, nor a common word with the question particle -kah. A new name is in no snapshot, so it stays a name.
3. `_cause_follows`: a lower-case movement word after the verb is no cause. Past it, a cause is read only after "oleh" ("tertekan tajam oleh aksi jual"). A capitalised word is a name and stays a cause ("terseret IHSG").
4. The files are snapshots. Rebuild them on purpose, review the diff and commit it; nothing reads the DB at runtime.

## Alternatives Considered
| Alternative | Pros | Cons | Why Not |
|---|---|---|---|
| Add the defects' words to the lists | smallest diff | the first held-out word fails again (3 rounds) | the loop ADR-031 stopped |
| Look words up in the DB at runtime | always current | `followup` and `causal_check` are pure; tests would need a DB | no gain for a slowly changing class |
| A POS tagger | the real answer to "what kind of word" | new dependency and model; Indonesian taggers are weak on news copy | out of proportion for two rules |

## Consequences
### Positive
- Both rules generalise past the words QA named. The same counts would decide a new case without a code change.
### Negative
- `common_words.txt` is about 390 KB in the repo.
- A name the archive mostly writes in lower case is read as a common word ("Bank", "Emas" open a thread question). That is the pre-9d9ad16 behaviour for those words.
- After a movement word, a cause without "oleh" is no longer checked ("tertekan lagi aksi jual"). Such a sentence is unnatural, and a cause marker ("akibat", "karena") is still its own link.
### Risks
- Stale snapshot. Mitigation: unknown words default to the old behaviour (a name; a cause), so a stale file only misses new common words.

## Dependencies
- ADR-021/022 (follow-up subject and adverb place), ADR-031 (the arc lists are frozen; this changes a rule for a regression, not a list for a synonym).

## Amendment 2026-11-10 (QA 2026-11-08: #450, #451, #452)
QA found that both classes hold members that break the rules they feed. Decision 2 and decision 1's movement half change. Decisions 3 and 4 stand.

**Decision 2, amended: the opener class is closed.** `_opening_subject` no longer refuses every common word. It refuses only `followup._SHARED_OPENERS`: time words, particles, hedges, modal and aspect adverbs, connectives and pronouns ("Kemarin / Kok / Kira-kira / Ternyata / Dia ... harganya?").
- Why: "lower case mid-sentence" also holds every common noun, and a commodity or a lower-case company name is the ordinary subject of a finance question ("Gula harganya naik?", "Timah labanya berapa?").
- No archive signal separates the two. `scripts/experiments/probe_opening_word_classes.py`, 60k articles: the share of uses governed by a lower-case content word is 0.45-0.90 for nouns and 0.04-0.69 for time words and particles. "malam tadi" and "kenapa kok" govern as often as "harga gula" does.
- Unlike nouns, the grammatical class is closed. Every member but "anda" (a courtesy capital) is in `common_words.txt`, and a test holds that.
- `common_words.txt` still decides the -kah form ("Benarkah", "Sungguhkah").
- Cost: an opener the list lacks opens its own subject. That is the pre-9d9ad16 behaviour, and it is rarer than a common noun.
- Routing check: 207 follow-ups. Every time word and particle routes as at HEAD, every common noun as on 84c3567, nothing else moved.

**Decision 1, amended: movement admission.** `scripts/build_word_classes.py`:
- admits no possessed -nya noun (`nya_words.is_reference`: eskalasinya, ekspornya, volumenya). `causal_check` reads such a word as a cause. "hanya" and "setidaknya" only end in -nya, so they stay;
- after a lower-case verb, it skips a capitalised word: a heading with no stop ("... menguat Mayoritas mata uang ..."), or a name. A title-case heading ("Rupiah Melemah Sepekan") still counts;
- drops "terjun" from the movement verbs, because "terjun payung" is a parachute jump.

The rebuild changed only `movement_words.txt`. `common_words.txt` is left at its 2026-11-07 snapshot.
