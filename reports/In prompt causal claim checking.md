# Make one source sentence prove each "karena"

**Recommendation: keep the rule in the prompt, but let code decide. Do not rely on the model checking itself, and do not make a second LLM call the gate.** The prompt should require that every *karena / akibat / dipicu / sehingga* sentence is backed by one verbatim source sentence. Code then checks that this one sentence contains a causal word and **both halves of the claim**: the effect and the cause. Your MK–Gibran sentence fails that test, because the two halves come from different source sentences. A quote check run on each half separately would have passed it. The evidence is consistent on three points. First, a model asked to check its own answer in the same pass rarely finds its own errors. Second, a real quote proves only that the words exist, not that the link exists. Third, causal-link errors are the kind that automated judges detect worst, and nobody has measured them in Indonesian. A separate judge call costs almost nothing at your volume (about $0.002 per check, roughly $0.10 a month). But it is about 75% accurate at best on English benchmarks and lenient. Run it in shadow mode, logging only, for two weeks, and make it a veto only if it catches something the code passed. The draft check written in SYS-152 (#342) needs one change: as written, it would pass the MK sentence.

## The prompt rule already failed once in six causal sentences

Your arc prompt already says, in effect, "use causal words only when the relation is written in the text, and name who said it". QA's hand check of the 10-08 to 10-11 arcs still found **one invented cause among six causal sentences**. That sentence is the MK one. It even names its source ("MK menyatakan …"), yet it joins two reasons that no article links ([SYS-150 hand check](https://github.com/imanueldrexel/news-scraping/issues/340)). The sample is tiny, but it matches the research.

Huang et al. asked models to "review the answer carefully and report any serious problems". Accuracy stayed flat or fell. When answers did change, they changed from right to wrong more often than from wrong to right: GPT-4 on GSM8K went **95.5 → 91.5 → 89.0** over two rounds of self-review ([Huang et al. 2023](https://arxiv.org/html/2310.01798v2)). A TACL survey found no prior work showing successful self-correction from prompted feedback, except on unusually suitable tasks. Self-correction works when the model gets **reliable external feedback** ([Kamoi et al. 2024](https://arxiv.org/abs/2406.01297)). Other work locates the bottleneck in finding the mistake, not in fixing a known one ([Tyen et al. 2023](https://arxiv.org/abs/2311.08516)).

Errors in a model's own output are especially hard for it to see. In one study, non-reasoning models corrected an error 62–88% of the time when it was presented as the user's, but only about **18–20% of the time when it sat in their own output** ([Self-Correction Bench](https://arxiv.org/html/2507.02778v2)). Thinking mode does not rescue grounded summaries either. On Vectara's benchmark, DeepSeek-R1 hallucinated **14.3%** when summarising given documents, against 3.9% for DeepSeek-V3 ([Vectara](https://vectara.com/blog/deepseek-r1-hallucinates-more-than-deepseek-v3)).

In-prompt checking is not worthless. In Chain-of-Verification, the "joint" variant, which verifies inside the same prompt as the draft, still beat no verification (Wikidata precision 0.17 → 0.29). But every variant that answered its check questions *without the draft in view* did better (0.32–0.36), because the joint variant "tends to repeat" the draft's hallucinations ([Dhuliawala et al. 2023](https://arxiv.org/html/2309.11495)). An in-prompt rule lowers the error rate, but it cannot be the last line of defence.

## A real quote proves the words exist, not the link

Requiring a quote is the strongest form of in-prompt checking, because finding a sentence is a lookup, not a judgement. Anthropic recommends exactly this ("find a direct quote … If you can't find a supporting quote for a claim, remove that claim"). It also says these techniques "don't eliminate" hallucinations, and it publishes no numbers ([Anthropic](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations)).

Where people have measured quotes, invented quotes are the minor problem. Frontier models' excerpts matched the source exactly 80–93% of the time, and DeepSeek V3.2's matched 71–77%. Most misses were formatting differences or faithful paraphrases ([VetScore 2026](https://arxiv.org/abs/2608.03675)). The major problem is a genuine quote that does not support the claim:

- **Clinical classification study.** 83–91% of quotes passed a strict substring check, but a second-model review rated only **48–79%** of those answers supported ([Show Your Work, medRxiv 2026](https://www.medrxiv.org/content/10.64898/2026.03.03.26346690v1.full)).
- **Veterinary study.** Humans judged almost half of the claims unverified, even though the attached excerpts were real ([VetScore](https://arxiv.org/abs/2608.03675)).
- **Clinical QA study.** One frontier model attached quotes to 98% of its claims but fully substantiated only **37%** ([Zhang et al. 2026](https://arxiv.org/abs/2609.15964)).

Your MK sentence is a case of exactly this failure. Both halves are true and quotable, and the error lives entirely in the word "karena". The research literature has a name for it: a **Discourse Link Error**, a wrong connective between statements that are each correct on their own ([FRANK, Pagnoni et al. 2021](https://arxiv.org/abs/2104.13346)). Checking claim by claim cannot see it. FActScore-style checking splits a sentence into independent "atomic facts" and assumes each one is checked on its own ([Min et al. 2023](https://arxiv.org/abs/2305.14251)). Split "MK cannot disqualify Gibran because the petition was inadmissible" that way and you get two supported facts, a 2/2 score, and the error is gone. A quote check run separately on each half is the same design and has the same blind spot.

This is why SYS-152 needs adjusting. Its draft check (b) accepts a causal sentence when the **cause clause** shares at least 60% of its content words with a source sentence that uses the same connective ([SYS-152](https://github.com/imanueldrexel/news-scraping/issues/342)). The source does contain "permohonan tidak dapat diterima *karena* mereka tidak memiliki kedudukan hukum". The cause clause, "permohonan tidak dapat diterima", matches that sentence fully, and the sentence has "karena". So the check passes, even though in the source that clause is the *effect*, not the cause.

Check (a) has a related weakness: it exempts any sentence carrying an attribution such as *menurut*. The MK sentence already attributes its claim to MK. Attribution tells the reader whose claim it is; it does not show that the source made the claim. The fix is to require **one** source sentence that contains a causal word together with both the effect and the cause, and to give attribution no exemption from that test.

## A separate judge is nearly free but weak on exactly this error

The research does favour a separate call over self-checking. A verifier that does not see the draft avoids copying the draft's errors ([Dhuliawala et al.](https://arxiv.org/html/2309.11495)). A judge shown the reference wrongly approved bad answers 3 times in 20, against 14 in 20 without it ([Zheng et al. 2023](https://arxiv.org/abs/2306.05685)). A judge from a different model family also avoids self-preference: models recognise their own text and rate it higher, and the bias grows with how well they recognise it ([Panickssery et al. 2024](https://arxiv.org/html/2404.13076)).

The problem is the ceiling, and for your error type it is lower still:

- **The best general checkers top out around 75–77%.** On LLM-AggreFact, the best checkers, both specialised models and frontier LLMs, reach only **75–77% balanced accuracy** ([leaderboard](https://llm-aggrefact.github.io/)). On FaithBench's hard cases they fall to about 50–58% ([Bao et al.](https://arxiv.org/abs/2410.13210)).
- **Discourse errors are where checkers do worst.** In FRANK, question-answer-based metrics were *negatively* correlated with discourse errors, and FactCC was "nearly uncorrelated" ([FRANK](https://arxiv.org/abs/2104.13346)).
- **Current benchmarks do not measure this error.** Later benchmarks stopped counting discourse errors at all: AggreFact dropped them as "uncommon" ([Tang et al. 2023](https://arxiv.org/abs/2205.12854)), and TofuEval did not annotate them ([TofuEval](https://arxiv.org/abs/2402.13249)). So the ~77% headline says nothing about invented "because" links.
- **Indonesian is weaker territory.** The best model trails humans by 13 points on expert Indonesian NLI ([IndoNLI](https://aclanthology.org/2021.emnlp-main.821.pdf)). Across 19 languages, NLI-based hallucination checkers agree with humans at a correlation of only 0.35–0.56 in high-resource languages, and often not significantly elsewhere ([Kang et al. 2024](https://arxiv.org/html/2402.10496v1)).
- **The good small checkers do not cover Indonesian.** MiniCheck and HHEM, the cheap specialised checkers, are English-only ([MiniCheck](https://arxiv.org/html/2404.10774v2); [HHEM](https://huggingface.co/vectara/hallucination_evaluation_model)).
- **Cheap judges are lenient.** Weak open-weight judges flagged about 20% of claims as unverified, where humans flagged nearly 50% ([VetScore](https://arxiv.org/abs/2608.03675)).

So a judge in the delivery path would be a coin flip with a bias toward approving, applied to an error class no one has measured, in a language no checker has been validated on.

Cost is not the issue. At DeepSeek's official peak prices for flash ($0.30 per million input tokens, $1.20 per million output tokens; [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing)), a judge call that reads about 6,000 tokens of source and writes 150 tokens costs about **$0.002**. At two calls a day that is about **$0.12 a month**, against a newsletter that already costs about $0.10–0.13 a day ([SYS-150](https://github.com/imanueldrexel/news-scraping/issues/340)). These are estimates from list prices: SumoPod's own pricing was not verified. The same pricing page also lists `deepseek-v4-flash` as a retired name that is still accepted, so confirm which model the alias now serves.

What a judge does add is operational risk:

- **Another way to fail.** DeepSeek's JSON mode "may occasionally return empty content" ([DeepSeek docs](https://api-docs.deepseek.com/guides/json_mode)).
- **Another dependency on the account balance.** The SumoPod balance has run out before.
- **Another verdict to audit.**

## The design: the prompt asks, code decides, a judge only watches

Each layer catches a different failure, which is the pattern the attribution literature converges on: generate the quote together with the claim, check it mechanically, then check that it supports the claim ([ALCE](https://arxiv.org/abs/2305.14627); [RARR](https://arxiv.org/abs/2210.08726)). Three details matter for your case:

- **Quote in the same call.** Citations produced during generation beat citations added afterwards by **47%** in citation recall ([ALCE](https://arxiv.org/abs/2305.14627)), so the quote belongs in the same call.
- **Evidence field first.** Evidence fields should come *before* the prose in the JSON. Models answering in strict JSON mode lose accuracy when the answer comes before the reasoning ([Tam et al. 2024](https://arxiv.org/html/2408.02442v3)).
- **Open question to the judge.** A judge should be asked an open question rather than a yes/no one, because models "agree with the way the question is stated" ([Dhuliawala et al.](https://arxiv.org/html/2309.11495)).

| Layer | What it does | What it sees |
|---|---|---|
| **Prompt (arc call)** | Adds a `"sebab"` list as the first JSON field. Each entry is `{"artikel": n, "kutipan": "<one sentence copied verbatim that contains the causal word, the effect and the cause>"}`. At most 2 entries; `[]` if none. Rule: every *karena / akibat / lantaran / dipicu / memicu / sehingga / imbas / disebabkan / menyebabkan* in the prose must rest on one entry, plus the existing rule to name who said it. | The same source texts as today |
| **Code gate (`story_arc.parse`, new refusal reason `"sebab"`)** | (1) Find every causal word in `judul`, `hari_ini`, `latar`, `agenda` and `sekilas`. (2) The `kutipan` must be a normalised substring of numbered source *n*: whitespace collapsed, quote marks and case unified, "…" allowed to bridge within one source. Up to two adjacent sentences are allowed, for "Hal ini menyebabkan …". (3) The `kutipan` must itself contain a causal word. Words are grouped into equivalence classes, so *karena* matches *lantaran* and *disebabkan*. (4) Split the prose sentence at its causal word: **the effect half and the cause half must each share at least 60% of their content words with that same `kutipan`**, using the `story_words` content-word definition. Swap the halves for forward connectives (*sehingga, menyebabkan, memicu*). (5) Attribution never exempts a sentence. On refusal, retry once with the detail: "this sentence is not supported by a single source sentence; drop the causal word or state the two facts separately". A second refusal triggers the existing fallback. | The prose and the shown source texts |
| **Judge (shadow only, 2 weeks)** | Runs for each causal sentence the code *passed*. First an open question ("According to the sources, why did [effect]?"), then a reason, then a verdict (supported / different reason / not stated). Prefer a different model family; the project already has a Gemini key, and 1–2 calls a day fits its free quota. Thinking off. It logs and never blocks. Promote it to a veto, which may remove a sentence but never rescue one, only if QA confirms a real catch the code missed. | One causal sentence, presented as "a reporter's sentence", plus the full source texts. Not the arc, not the prompt, not the model's `kutipan` |

Run against QA's six hand-checked sentences, the code gate behaves as intended:

- **Passes (four):** PHK (verbatim), BPIH (*lantaran … akibat* near-verbatim) and Defisit (*disebabkan oleh*) pass. OMC passes through the two-adjacent-sentence allowance.
- **Refused (MK):** the MK sentence is refused, because "tidak dapat mendiskualifikasi" and "permohonan tidak dapat diterima" never share a source sentence with a causal word.
- **Likely false refusal (Ojol):** the quoted source fragment ("mensinergikan dengan undang-undang lain …") carries no causal word. A false refusal costs one retry, after which the model drops the causal word or states the two facts separately. An invented cause costs a false fact in a delivered newsletter. Accepting that trade is the point of failing closed.

These six sentences should become the unit-test fixtures, with MK as the mutant-killing case.

The incremental cost is about 60–100 extra output tokens per arc that uses a causal word, plus an occasional retry of one arc call. Both are fractions of a cent a day.

## Conclusion

The research reframes the question. "Inside the prompt or in a separate call" matters less than **what the check is anchored to**. A self-check anchored to nothing fails. A judge anchored to the whole source is cheap but unreliable on this error and unvalidated in Indonesian. A string check anchored to **a single source sentence that must hold the cause, the effect and the causal word together** catches the exact failure you saw, deterministically, and can be mutation-tested like every other arc guard. The model's quote is useful as a pointer for the code, not as proof.

What remains unknown is how often LLM news summaries invent causal links, and how well any judge catches them. No study isolates that, in any language. Your hand check and the two-week shadow log will produce the only measurement that exists for this pipeline. Read the shadow log before deciding whether the judge earns a veto.
