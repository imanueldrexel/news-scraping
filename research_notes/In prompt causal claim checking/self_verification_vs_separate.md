# Can an LLM verify its own output in the same generation pass? In-prompt self-verification vs. separate verification calls

Scope note: the strongest primary evidence on *intrinsic* self-correction is on reasoning and QA (GSM8K, CommonSenseQA, HotpotQA). Evidence specific to *grounded* generation (summaries and RAG answers checked against a source) comes mainly from CoVe (closed-book factual generation), CRITIC (QA with and without retrieval), and the fact-checking/judge literature (MiniCheck/LLM-AggreFact, SummEdits, self-preference). Where a number comes from math or reasoning, these notes say so.

## Q1. What do Huang et al. ("LLMs Cannot Self-Correct Reasoning Yet", ICLR 2024) and related work find about intrinsic self-correction without external feedback?

### Takeaway
Without an external signal, asking the same model to "review your answer and find problems" leaves accuracy flat or makes it worse. When answers change, they more often go from correct to incorrect than the other way. Earlier reported gains came from oracle labels, which told the model when to stop, or from weak initial prompts. The 2024 TACL survey (Kamoi et al.) generalises this: no prior work shows successful self-correction from prompted-LLM feedback, except on tasks unusually suited to it. What does work is reliable external feedback or large-scale fine-tuning.

### Cited Findings
- Huang et al. used this self-correction instruction: "Assume that this answer could be either correct or incorrect. Review the answer carefully and report any serious problems you find." — [Huang et al. 2023, arXiv 2310.01798v2](https://arxiv.org/html/2310.01798v2)
- GSM8K, intrinsic self-correction (standard → round 1 → round 2). GPT-3.5: 75.9 → 75.1 → 74.7. GPT-4: 95.5 → 91.5 → 89.0. GPT-4-Turbo: 91.5 → 88.0 → 90.0. Llama-2: 62.0 → 43.5 → 36.5. — [Huang et al. 2023](https://arxiv.org/html/2310.01798v2)
- CommonSenseQA. GPT-3.5: 75.8 → 38.1 → 41.8. GPT-4: 82.0 → 79.5 → 80.0. GPT-4-Turbo: 84.0 → 81.5 → 83.0. Llama-2: 64.0 → 37.5 → 36.5. The paper attributes the large correct→incorrect share on CSQA to plausible wrong options. — [Huang et al. 2023](https://arxiv.org/html/2310.01798v2)
- HotpotQA (multi-hop factual QA, the closest of its tasks to grounding). GPT-3.5: 26.0 → 25.0 → 25.0. GPT-4: 49.0 → 49.0 → 43.0. — [Huang et al. 2023](https://arxiv.org/html/2310.01798v2) (numbers from the v2 HTML tables via the fetch tool; worth a spot-check against the PDF before quoting)
- Answer-change analysis (GPT-3.5, GSM8K): 74.7% of answers did not change. Among those that did, correct→incorrect outnumbered incorrect→correct. — [Huang et al. 2023](https://arxiv.org/html/2310.01798v2)
- With oracle labels (stop correcting once the answer is right), GPT-3.5 on GSM8K rises from 75.9 to 84.3. The authors argue that this gain reflects access to ground truth, not genuine self-correction. — [Huang et al. 2023](https://arxiv.org/html/2310.01798v2)
- At an equal number of responses, multi-agent debate (83.0% on GSM8K) underperformed self-consistency over 9 samples (88.2%). Debate's apparent gains are mostly explained by ensembling. — [Huang et al. 2023](https://arxiv.org/html/2310.01798v2)
- Prompt-design artefact: on Constrained Generation, the reported self-correction improvement disappeared once the initial prompt gave the full task specification instead of splitting the instructions between the first prompt and the feedback prompt. — [Huang et al. 2023](https://arxiv.org/html/2310.01798v2)
- The authors' explanation: models cannot reliably judge whether their own answer is correct, and a feedback prompt biases the model toward changing the answer. — [Huang et al. 2023](https://arxiv.org/html/2310.01798v2)
- Kamoi et al. (TACL 2024) conclude that "no prior work demonstrates successful self-correction with feedback from prompted LLMs, except for studies in tasks that are exceptionally suited for self-correction." Self-correction "works well in tasks that can use reliable external feedback", and large-scale fine-tuning enables it. They also find many prior frameworks impractical or evaluated unfairly, inflating self-correction results. — [Kamoi et al. 2024, arXiv 2406.01297](https://arxiv.org/abs/2406.01297)
- Tyen et al. (2023, BIG-Bench Mistake): "poor self-correction performance stems from LLMs' inability to find logical mistakes, rather than their ability to correct a known mistake". Given the error location (backtracking), performance improves across 5 reasoning tasks. — [Tyen et al. 2023, arXiv 2311.08516](https://arxiv.org/abs/2311.08516)
- SummEdits (EMNLP 2023), on detecting inconsistencies between a summary and its source: most LLMs score close to random chance. The best, GPT-4, is still about 8% below estimated human performance. — [Laban et al. 2023](https://aclanthology.org/2023.emnlp-main.600)

### Inferences
- Detection, not repair, is the bottleneck. A "check your answer before responding" instruction asks the model to do the part it is worst at (finding its own error), with no new information, in the same context that produced the error.
- For grounded summarization, the verification step needs an independent signal: the source text re-read claim by claim, a retrieval or tool result, or a separate checker. A generic "be careful" instruction is not such a signal.

### Gaps
- Huang et al. evaluate reasoning and QA, not source-grounded summarization. I found no primary study that measures exactly "append 'only state claims supported by the source; check before answering'" vs. "separate verifier call" on summaries with human-labeled unsupported-claim rates.
- I could not retrieve the exact per-category percentages from Huang et al.'s Figure 1, only its direction.
- Tyen et al.'s exact mistake-finding accuracies were not on the abstract page and were not retrieved.

## Q2. Chain-of-Verification (Dhuliawala et al., 2023): joint vs. 2-step vs. factored vs. factor+revise, and why independent verification helps

### Takeaway
Every CoVe variant beats the baseline, but the variants that answer the verification questions without the original draft in context (2-step, factored, factor+revise) beat "joint", where planning and answering the verification questions happen in the same prompt as the draft. Joint verification tends to repeat the draft's hallucinations. On biographies, the full factor+revise pipeline lifts FactScore from 55.9 to 71.4 (Llama 65B).

### Cited Findings
- Wikidata list questions, Llama 65B (precision / correct entities / hallucinated entities per answer). Few-shot baseline: 0.17 / 0.59 / 2.95. Joint: 0.29 / 0.41 / 0.98. 2-step: 0.36 / 0.38 / 0.68. Factored: 0.32 / 0.38 / 0.79. — [Dhuliawala et al. 2023, arXiv 2309.11495](https://arxiv.org/html/2309.11495)
- Wiki-Category list questions, Llama 65B. Baseline: 0.12 / 0.55 / 4.05. Joint: 0.15 / 0.30 / 1.69. 2-step: 0.21 / 0.50 / 0.52. Factored: 0.22 / 0.52 / 1.52. — [Dhuliawala et al. 2023](https://arxiv.org/html/2309.11495)
- MultiSpanQA closed-book (F1 / precision / recall). Baseline: 0.39 / 0.40 / 0.38. Joint: 0.46 / 0.50 / 0.42. Factored: 0.48 / 0.50 / 0.46. — [Dhuliawala et al. 2023](https://arxiv.org/html/2309.11495)
- Longform biographies, FactScore (average facts per bio). Llama 65B few-shot: 55.9 (16.6). Joint: 60.8 (12.8). Factored: 63.7 (11.7). Factor+revise: 71.4 (12.3). Reference systems: InstructGPT 41.1, ChatGPT 58.7, PerplexityAI 61.6, so Llama 65B with factor+revise beats the retrieval-backed PerplexityAI. — [Dhuliawala et al. 2023](https://arxiv.org/html/2309.11495)
- Why joint is worse: in the joint setting the verification answers have to condition on the initial response, so they tend to repeat its hallucinations, which defeats the purpose. The factored variant answers each verification question in a separate prompt with no access to the baseline response. — [Dhuliawala et al. 2023](https://arxiv.org/html/2309.11495)
- Why short independent questions help: on Wikidata the baseline list answers were about 17% correct, but the same model answered the individual verification questions about 70% correctly. Focused short-form queries are answered more accurately than the same facts embedded in long-form generation. — [Dhuliawala et al. 2023](https://arxiv.org/html/2309.11495)
- Yes/no verification questions ("Is X true?") underperformed open-ended ones: the model "tends to agree with the way the question is stated, even if stated incorrectly." — [Dhuliawala et al. 2023](https://arxiv.org/html/2309.11495)
- Precision gains come partly from saying less. On biographies the average number of facts drops from 16.6 to 11.7–12.8. On Wikidata, correct entities per answer fall from 0.59 to 0.38–0.41. Verification removes claims, including some true ones. — [Dhuliawala et al. 2023](https://arxiv.org/html/2309.11495)

### Inferences
- For a "list only claims supported by the source" pipeline, CoVe implies that the check should run with the draft hidden from the checker, and should ask open questions ("What does the source say about X's cause?") rather than leading yes/no ones ("Does the source say X caused Y?").
- Even joint CoVe, a single prompt, beats doing nothing (Wikidata precision 0.17 → 0.29; FactScore 55.9 → 60.8). In-prompt structured verification is therefore not useless, only clearly weaker than a factored check.
- Expect recall loss. A verifier that strips unsupported claims will also strip some true ones. Measure both precision and claims kept.

### Gaps
- CoVe is closed-book (verification against the model's own parametric knowledge), not verification against a supplied source document. I found no direct replication of joint vs. factored on source-grounded summarization.
- The 2-step results on longform were not in the retrieved text.

## Q3. Self-Refine, Reflexion, CRITIC: when does self-critique help, and when does it need external tools or feedback?

### Takeaway
Same-model critique-and-revise (Self-Refine) helps on open-ended, preference-style tasks (style, dialogue, constraint satisfaction), where "better" is easy to judge. It gives essentially nothing on correctness tasks such as math, because the model cannot find its own errors. CRITIC isolates the tool effect: the same verify-then-correct loop with search or a code interpreter beats the tool-free version by 2–22 F1 points on QA. The authors call LLMs unreliable at validating their own results.

### Cited Findings
- Self-Refine (Madaan et al. 2023): one LLM acts as generator, feedback provider and refiner, with about 20% absolute average improvement over one-step generation across 7 tasks (GPT-3.5, ChatGPT, GPT-4). — [Madaan et al. 2023, arXiv 2303.17651](https://arxiv.org/abs/2303.17651)
- Self-Refine GPT-4 gains are large on subjective or constraint tasks: Sentiment Reversal 3.8 → 36.2, Dialogue Response 25.4 → 74.6, Code Readability 27.4 → 56.2, Acronym Generation 30.4 → 56.0, Constrained Generation 15.0 → 45.0, Code Optimization 27.3 → 36.0. — [Madaan et al. 2023](https://arxiv.org/html/2303.17651)
- Self-Refine on Math Reasoning: minimal gains (0–0.2 points) across models. The authors give two reasons: the model cannot "accurately identify whether there is any error", and "a consistent-looking reasoning chain can deceive LLMs". With oracle (external) correctness feedback, GPT-3 improved by 4.8 points. — [Madaan et al. 2023](https://arxiv.org/html/2303.17651)
- Feedback-quality ablation (Self-Refine specific feedback / generic feedback / no feedback). Sentiment Reversal: 43.2 / 31.2 / 0. Acronym: 56.4 / 54.0 / 48.0. Code Optimization: 27.5 / 26.0 / 24.8. — [Madaan et al. 2023](https://arxiv.org/html/2303.17651)
- Vicuna-13B could not follow the feedback and refine prompts and produced hallucinated "refinements". Self-critique depends on a strong instruction-following model. — [Madaan et al. 2023](https://arxiv.org/html/2303.17651)
- Huang et al. note that Self-Refine's Constrained Generation gain vanished once the initial prompt fully specified the task (see Q1). — [Huang et al. 2023](https://arxiv.org/html/2310.01798v2)
- CRITIC (Gou et al., ICLR 2024), free-form QA F1, with tool vs. without tool (self-critique only). text-davinci-003: AmbigNQ 80.6 vs. 58.3, TriviaQA 79.5 vs. 74.7, HotpotQA 50.5 vs. 46.1. ChatGPT: AmbigNQ 74.9 vs. 67.3, TriviaQA 81.7 vs. 79.9, HotpotQA 52.9 vs. 46.1. — [Gou et al. 2023, arXiv 2305.11738](https://arxiv.org/html/2305.11738)
- CRITIC on math and toxicity, with tool vs. without. GSM8K (ChatGPT): 78.2 vs. 77.0. TabMWP (davinci-003): 87.6 vs. 84.9. Toxicity probability: 0.173 vs. 0.339 (ChatGPT) and 0.180 vs. 0.353 (davinci-003), about 49% lower with the Perspective API tool. — [Gou et al. 2023](https://arxiv.org/html/2305.11738)
- CRITIC authors: "exclusive reliance on self-correction without external feedback may yield modest improvements or even deteriorate performance". They report the "unreliability of all tested LLMs, when it comes to validating their own results", and conclude that external tool feedback is "crucial for consistent self-improvement". — [Gou et al. 2023](https://arxiv.org/html/2305.11738)
- Kamoi et al. classify such tool and verifier setups as "reliable external feedback", the condition under which self-correction works. — [Kamoi et al. 2024](https://arxiv.org/abs/2406.01297)

### Inferences
- In source-grounded summarization the source document is the external feedback. A check that re-reads the source per claim (quote extraction, an entailment check) is closer to CRITIC-with-tool than to intrinsic self-correction. A bare "double-check your summary" is the tool-free condition.
- Self-Refine's gains are on tasks where a fluent model's taste is enough to judge quality. Whether "this causal claim is supported by the article" is such a task is doubtful. It is a correctness judgment, closer to the math and QA cases where gains vanish.

### Gaps
- Reflexion (Shinn et al. 2023) was not fetched. Its gains rely on environment or test-case feedback (e.g. unit tests for code). That is from memory and unverified here, so do not cite it without checking.
- CRITIC's tool-free numbers compared against the plain CoT baseline were not retrieved, so I cannot state whether tool-free CRITIC beat or trailed the baseline on each QA dataset.

## Q4. LLM-as-judge / separate verifier calls for faithfulness: accuracy and self-preference bias

### Takeaway
Separate checkers against a grounding document reach about 74–75% balanced accuracy on a broad human-labeled benchmark (LLM-AggreFact). A 770M specialised checker (MiniCheck-FT5) matches GPT-4 at more than 400x lower cost. Harder edited-summary benchmarks show most LLMs near chance. When the judge is the same model that wrote the text, self-preference is a measured risk: models can recognise their own summaries and favour them, and the bias rises with self-recognition. A verifier from a different model family, or a non-LLM entailment model, sidesteps this.

### Cited Findings
- LLM-AggreFact (10 human-labeled datasets: CNN, XSum, MediaSum, MeetingBank summarization; ExpertQA and LFQA RAG; AggreFact, TofuEval, WiCE, REVEAL, ClaimVerify, FactCheck-GPT), balanced accuracy: GPT-4 75.3%, MiniCheck-FT5 74.7%, Claude-3 Opus 74.1%, AlignScore 70.4%. — [Tang et al. 2024 (MiniCheck), arXiv 2404.10774](https://arxiv.org/html/2404.10774)
- Cost: MiniCheck-FT5 is "more than 400 times cheaper" than GPT-4, $0.24 vs. $107 across about 13,000 test examples. — [Tang et al. 2024](https://arxiv.org/html/2404.10774)
- Explicit claim decomposition "shows near-zero performance change for GPT-4 and mixed changes for specialized fact-checkers". Splitting into atomic claims did not by itself improve checking accuracy on this benchmark. — [Tang et al. 2024](https://arxiv.org/html/2404.10774)
- SummEdits: most LLMs score close to random at detecting factual inconsistencies in summaries, and GPT-4 is about 8% below estimated human performance. Inter-annotator agreement is about 0.9. — [Laban et al. 2023, EMNLP](https://aclanthology.org/2023.emnlp-main.600)
- Self-recognition, out of the box (pairwise, summarization): GPT-4 67.2% on XSUM and 74.7% on CNN/DailyMail. Llama 2 is near chance: 51.4% and 50.5%. — [Panickssery et al. 2024, "LLM Evaluators Recognize and Favor Their Own Generations", arXiv 2404.13076](https://arxiv.org/html/2404.13076)
- After fine-tuning on 500 examples, GPT-3.5 and Llama 2 exceed 90% self-recognition, and self-preference rises with it. The authors report a linear correlation between self-recognition and the strength of self-preference. Their conclusion is that LLM evaluators systematically rate their own outputs higher than comparable texts from other models or humans. — [Panickssery et al. 2024](https://arxiv.org/html/2404.13076)
- Self-Correction Bench: when the same error is presented as coming from the user, non-reasoning models correct it 62–88% of the time on complex tasks. When it appears in their own output, they correct it about 18–20% of the time, an average "blind spot" of 64.5% across 14 models. — [Tsui 2025, arXiv 2507.02778](https://arxiv.org/html/2507.02778v2)
- Anthropic's guidance offers in-prompt and multi-pass options for hallucination control. In-prompt: allow "I don't know"; for long documents (more than 20k tokens) "extract word-for-word quotes first"; "verify with citations", i.e. "after drafting, review each claim… find a direct quote… If you can't find a supporting quote for a claim, remove that claim". Multi-pass: "Best-of-N verification" (inconsistencies across runs signal hallucination) and "iterative refinement" via follow-up prompts. It notes these "don't eliminate them entirely." — [Anthropic, "Reduce hallucinations"](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations)

### Inferences
- The Self-Correction Bench gap (errors framed as someone else's are caught at roughly 3–4x the rate) is direct evidence for presenting the draft to the checker as external text in a new call, not as the model's own continuation.
- Self-preference is measured on pairwise quality judgments of summaries, not on binary claim-support verdicts. It is plausible, but not demonstrated in these sources, that a same-model claim checker is more lenient on its own claims. A cross-family judge or an NLI/MiniCheck-style model avoids the question.
- A balanced accuracy of about 75% means a separate checker is a filter, not an oracle. Pair it with human spot-checks and report its false-negative rate on your own labeled sample.
- Anthropic's "verify with citations" pattern is a same-call check, but it is anchored on retrieving an exact quote from the source. That turns the task into a lookup rather than an intrinsic judgment, which is the strongest variant of in-prompt checking.

### Gaps
- I found no study measuring the same model's faithfulness-judge accuracy on its own vs. others' summaries with binary support labels (as opposed to pairwise preference).
- I did not retrieve any vendor-published numbers showing how much the quote-first or retract-unsupported-claims instructions reduce hallucination. Anthropic's page gives no figures.
- OpenAI's hallucination guidance was not retrieved.

## Q5. Do reasoning or "thinking" models (2024–2026) change the conclusion?

### Takeaway
The evidence is mixed. RL-trained reasoning models do self-correct inside their chain of thought far more readily: Self-Correction Bench finds minimal or negative blind spots for R1 and QwQ. Simply appending "Wait" to a non-reasoning model's output cuts the blind spot by 89.3%. But reasoning models are not more faithful summarisers. On Vectara's grounded-summarization benchmark, DeepSeek-R1 hallucinates 14.3% vs. 3.9% for DeepSeek-V3, and o1 2.4% vs. 1.5% for GPT-4o. OpenAI reported o3 and o4-mini hallucinating more than o1 on PersonQA. In-CoT self-verification helps on checkable reasoning, but it is not evidence that thinking models reliably catch unsupported claims against a source.

### Cited Findings
- Self-Correction Bench (Tsui, NeurIPS 2025): across 14 non-reasoning models the average blind spot is 64.5%. Reasoning models (DeepSeek-R1, QwQ) show minimal or negative blind spots. Appending "Wait" reduces blind spots by 89.3% and raises accuracy by 156% macro-average. The author attributes the blind spot to SFT data rarely containing error-correction sequences (correction markers in under 1–2% of instruction examples), while RL-generated reasoning data has them in 99% of samples. — [Tsui 2025, arXiv 2507.02778](https://arxiv.org/html/2507.02778v2); [NeurIPS 2025 listing](https://neurips.cc/virtual/2025/122384)
- Vectara HHEM 2.1 (summarizing given documents): DeepSeek-R1 14.3% vs. DeepSeek-V3 3.9%, and GPT-o1 2.4% vs. GPT-4o 1.5%. On Google's FACTS (three LLM judges averaged) the gap was smaller: R1 3.09–4.37% vs. V3 1.99–2.99%. Vectara says it is "too early" to call hallucination an inherent cost of reasoning. — [Vectara blog](https://vectara.com/blog/deepseek-r1-hallucinates-more-than-deepseek-v3)
- OpenAI's o3/o4-mini system card (as reported) gives PersonQA hallucination rates of o3 33%, o4-mini 48%, o1 16%. o3 "tends to make more claims overall, leading to more accurate claims as well as more inaccurate/hallucinated claims". — [Techzine](https://www.techzine.eu/news/applications/130720/new-openai-models-hallucinate-more-often-than-their-predecessors/), [Yahoo/TechCrunch syndication](https://tech.yahoo.com/articles/openais-o3-o4-mini-hallucinate-173655834.html) (secondary; the primary system card PDF was not fetched)
- Mechanistic work finds identifiable self-verification circuitry in an R1-recipe model. As few as three attention heads can disable self-verification on CountDown, and similar components exist in DeepSeek-R1. — [Lee et al. 2025, "The Geometry of Self-Verification in a Task-Specific Reasoning Model", arXiv 2504.14379](https://arxiv.org/html/2504.14379v2)
- Anthropic recommends extended thinking for chain-of-thought verification as a debugging aid: review the summarized reasoning "when an answer looks wrong". It is not presented as a guarantee. — [Anthropic, "Reduce hallucinations"](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations)

### Inferences
- Thinking models narrow the "can't notice my own error" gap for problems with a checkable answer. That does not carry over to faithfulness to a source: two independent benchmarks show reasoning variants hallucinating as much as or more than their base models on grounded summarization.
- A plausible mechanism, consistent with the o3 note, is that reasoning models assert more and infer more beyond the text. That is the direction that produces unsupported causal claims. Even with a thinking model, a separate source-anchored check remains warranted.

### Gaps
- I found no controlled 2025–2026 study comparing a reasoning model's same-call self-check against a separate verifier call on grounded summarization.
- The OpenAI system card numbers are cited via press coverage, not the primary PDF.
- Self-Correction Bench uses injected errors in reasoning tasks, not unsupported claims in summaries.
