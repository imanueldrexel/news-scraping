# Cost, latency and failure modes of hallucination checks in a cheap-model (DeepSeek flash-class) JSON summarization pipeline

Research date: 2026-10-17. Paper figures are from 2023-2024 unless noted; pricing fetched 2026-10-17.

## Q1. What do small dedicated fact-checkers (MiniCheck, Bespoke-MiniCheck-7B, HHEM) achieve vs GPT-4-class judges on LLM-AggreFact, and at what cost?

### Takeaway
Small fact-checkers trained for grounding (0.1B-7B parameters) match or beat GPT-4-class judges on English grounding benchmarks. Balanced accuracy for all of them sits around 74-77%, so even the best checker gets roughly 1 in 4 cases wrong. They run at about 1/400th of GPT-4's cost. All of the open models are English-only, which matters for Indonesian text.

### Cited Findings
- LLM-AggreFact leaderboard, average balanced accuracy over 11 datasets: Bespoke-MiniCheck-7B 77.4; Claude-3.5 Sonnet 77.2; Granite Guardian 3.3 (8B) 76.5; Mistral-Large 2 (123B) 76.5; gpt-4o-2024-05-13 75.9; FactCG-DeBERTa-L (0.4B) 75.6; Qwen2.5-72B-Instruct 75.6; MiniCheck-Flan-T5-L (0.8B) 75.0; Llama-3.3-70B 74.5; Llama-3.1-405B 74.4; QwQ-32B-Preview 71.8. The page shows 11 of 39 models and gives no update date. No DeepSeek model is shown. — [LLM-AggreFact leaderboard](https://llm-aggrefact.github.io/)
- MiniCheck paper (Tang et al., arXiv Apr 2024, EMNLP 2024), Table 2: MiniCheck-FT5 (770M) 74.7% vs GPT-4 75.3%, Claude-3 Opus 74.1%, Mistral-Large 73.4%, AlignScore 70.4%; MiniCheck-RBTA 72.7%, MiniCheck-DBTA 72.6%. — [MiniCheck (arXiv 2404.10774 HTML)](https://arxiv.org/html/2404.10774v2)
- Cost to run the 13K-example test set: GPT-4 $107, Claude-3 Opus $165, MiniCheck-FT5 $0.24. The paper describes this as "GPT-4-level performance but for 400x lower cost". — [MiniCheck](https://arxiv.org/html/2404.10774v2); [abstract](https://arxiv.org/abs/2404.10774)
- MiniCheck limitations as stated by its authors: it was "trained exclusively on English data", and the benchmark has no cases that need evidence spread across separate passages or documents. — [MiniCheck](https://arxiv.org/html/2404.10774v2)
- Bespoke-MiniCheck-7B: fine-tuned from internlm2_5-7b-chat; English; default chunk size 32K tokens. Throughput is above 500 docs/min with vLLM on one A6000 (the same figure is given for MiniCheck-Flan-T5-L). No hosted inference provider. — [HF model card](https://huggingface.co/bespokelabs/Bespoke-MiniCheck-7B)
- Bespoke-MiniCheck-7B licence, conflicting sources: the HF card says "CC BY-NC 4.0" and asks commercial users to contact Bespoke Labs. — [HF card](https://huggingface.co/bespokelabs/Bespoke-MiniCheck-7B). The MiniCheck GitHub README calls it "commercially useable". — [MiniCheck GitHub](https://github.com/Liyan06/MiniCheck)
- MiniCheck repo: automatic prefix caching cut inference on a 29K-example test set from 55 to 30 minutes on one A6000. — [MiniCheck GitHub](https://github.com/Liyan06/MiniCheck)
- Vectara HHEM-2.1-Open: based on flan-t5-base, about 0.1B parameters, under 600MB RAM at fp32, no context length cap (HHEM-1.0 was capped at 512 tokens). About 1.5 s for a 2k-token input on a modern x86 CPU. English only. The commercial HHEM-2.3 covers en/de/fr/pt/es/ar/zh/ko/ru/ja/hi, which does not include Indonesian. — [HHEM model card](https://huggingface.co/vectara/hallucination_evaluation_model)
- HHEM-2.1-Open balanced accuracy (vendor-reported):

  | Benchmark | HHEM-2.1-Open | GPT-3.5-Turbo | GPT-4 |
  |---|---|---|---|
  | AggreFact-SOTA | 76.55% | 72.19% | 73.78% |
  | RAGTruth-Summ | 64.42% | 58.49% | 62.62% |
  | RAGTruth-QA | 74.28% | 56.16% | 74.11% |

  On RAGTruth-QA, F1 is 60.00 (HHEM) vs 25.00 (GPT-3.5) vs 57.78 (GPT-4). — [HHEM model card](https://huggingface.co/vectara/hallucination_evaluation_model)

### Inferences
- Detector choice matters less than the ceiling: the best checkers score about 75-77%. A second-pass check reduces errors but does not certify a summary.
- RAGTruth-Summ, the summarization-specific split, is lower (HHEM 64%, GPT-4 63%) than the QA or AggreFact numbers. Expect a noisier verdict on news summaries than the headline averages suggest.
- A local 0.1-0.8B checker on CPU (about 1-2 s per 2k tokens) costs essentially nothing. But every open checker is English-only, so Indonesian articles would need translating first, or a multilingual NLI model would be used out of its tested domain (see Q5).

### Gaps
- The leaderboard snapshot does not show DeepSeek (V3/V4/flash), gpt-4o-mini, Gemini Flash or ~8B general instruct models used as judges. I found no published LLM-AggreFact number for a DeepSeek flash-class judge.
- No benchmark measures any of these checkers on Indonesian.

## Q2. Does forcing structured/JSON output or extra fields hurt reasoning or faithfulness in smaller models?

### Takeaway
Yes, for reasoning, and most under strict JSON mode. Accuracy collapses when the schema puts the answer before the reasoning. For classification-like outputs (a verdict label), JSON constraints help. Each extra constraint also lowers the odds that all of them are satisfied, and small models degrade sooner.

### Cited Findings
- Tam et al. 2024, "Let Me Speak Freely?" Models: GPT-3.5-Turbo, Claude-3-Haiku, Gemini-1.5-Flash, LLaMA-3-8B, Gemma-2-9B (plus GPT-4o-mini and Mistral-7B in the appendix). Results:

  | Task | Free text | JSON-mode | Format-restricting instructions | NL-to-Format (two-step) |
  |---|---|---|---|---|
  | GSM8K | ~76-89% | 30-50% | 60-87% | 71-88% |
  | Last Letter | 56-70% | 1-28% | 65-85% | ~83-85% |

  — [Tam et al. HTML](https://arxiv.org/html/2408.02442v3); abstract: "stricter format constraints generally lead to greater performance degradation in reasoning tasks" — [arXiv 2408.02442](https://arxiv.org/abs/2408.02442)
- Mechanism (Tam et al.): in some tasks, 100% of GPT-3.5-Turbo JSON-mode responses put the "answer" key before the "reason" key, which defeats zero-shot chain of thought. The gap persisted even when parsing failures were near zero. — [Tam et al.](https://arxiv.org/html/2408.02442v3)
- Classification is the exception: on DDXPlus, Gemini-1.5-Flash went from 41.6% (free text) to 60.3% (JSON-mode), because JSON restricts the answer space. — [Tam et al.](https://arxiv.org/html/2408.02442v3)
- Instruction count: ManyIFEval finds a "curse of instructions". Per-instruction accuracy stays high while the rate of satisfying all instructions at once falls as instructions are added. — [When Instructions Multiply (arXiv 2509.21051)](https://arxiv.org/pdf/2509.21051)
- IFScale (2025), up to 500 keyword instructions: at 500, Gemini 2.5 Pro 68.9%, Claude 3.7 Sonnet 52.7%, GPT-4o 15.4%, Llama 4 Scout 6.7%. Some models decay exponentially after 50-100 instructions. — [IFScale (arXiv 2507.11538)](https://arxiv.org/abs/2507.11538) (figures as surfaced in search results; not checked against the PDF)
- DeepSeek's own JSON-mode caveats: you must put the word "json" and an example format in the prompt; you must size max_tokens "to prevent the JSON string from being truncated midway"; and "the API may occasionally return empty content". — [DeepSeek JSON mode docs](https://api-docs.deepseek.com/guides/json_mode)
- Asking for a verbatim quote per claim does not by itself make the claim supported. In a 12-LLM clinical QA study (Sep 2026), most models attached verbatim quotes to over 90% of claims from prompting alone. Claude Opus 5 attached quotes to 98.0% of its claims but fully substantiated only 37.1%. Lightweight models (claude-haiku-4.5 named) were notably weaker at attaching quotes. — [Zhang et al., arXiv 2609.15964](https://arxiv.org/abs/2609.15964); [PDF](https://arxiv.org/pdf/2609.15964)

### Inferences
- If extra JSON fields are added (an evidence quote per claim, a self-check flag), put the reasoning or evidence fields before the verdict or summary fields in the schema. Better still, write freely first and then convert to JSON in a second pass (NL-to-Format), which recovered most of the loss in Tam et al.
- An in-prompt quote field is cheap to check deterministically (exact substring match). Passing that check only shows the quote exists. It does not show the claim follows from it: the 98% vs 37% gap above.
- Each added field or rule is one more constraint competing with existing word limits and other rules. Smaller or cheaper models lose the "all constraints met" rate fastest.
- Longer JSON (quotes per claim) raises the risk of max_tokens truncation and the empty-content failure that DeepSeek documents. Both need a retry path.

### Gaps
- Tam et al. did not test DeepSeek models or schemas that ask for evidence quotes.
- I found no published measurement of how much an extra "evidence quote" field changes summary quality or length for a flash-class model. This would have to be measured locally (an A/B on replayed days).

## Q3. Judge sycophancy, self-preference and position bias when a model verifies its own output

### Takeaway
LLM judges favor their own outputs, and the bias grows with how well they recognize their own text. They are also swayed by answer order, verbosity and even single meaningless tokens. Weaker judges are much worse than GPT-4-class ones. Self-verification by the same cheap model that wrote the summary is the weakest setup.

### Cited Findings
- Panickssery et al. 2024: GPT-4 and Llama 2 can tell their own outputs from other LLMs' and humans' with "non-trivial accuracy" out of the box. Fine-tuning shows "a linear correlation between self-recognition capability and the strength of self-preference bias", and this holds against straightforward confounders. — [arXiv 2404.13076](https://arxiv.org/abs/2404.13076)
- Zheng et al. 2023 (MT-Bench / LLM-as-a-judge), position bias, Table 2. Consistency = % of pairs judged the same after swapping order:

  | Judge | Prompt | Consistency | Biased to first | Biased to second | Error |
  |---|---|---|---|---|---|
  | Claude-v1 | default | 23.8% | 75.0% | 0.0% | 1.2% |
  | GPT-3.5 | default | 46.2% | 50.0% | 1.2% | 2.5% |
  | GPT-4 | default | 65.0% | 30.0% | 5.0% | 0.0% |

  — [arXiv 2306.05685](https://arxiv.org/abs/2306.05685) (Table 2 of the PDF)
- Zheng et al., verbosity ("repetitive list" attack, 23 answers): failure rate Claude-v1 91.3%, GPT-3.5 91.3%, GPT-4 8.7%. — [arXiv 2306.05685](https://arxiv.org/abs/2306.05685)
- Zheng et al., grading math: GPT-4 called an incorrect answer correct in 14/20 cases with the default prompt, 6/20 with chain of thought, and 3/20 when given a reference answer. — [arXiv 2306.05685](https://arxiv.org/abs/2306.05685)
- Zheng et al., self-enhancement: GPT-4 gave itself a +10% win rate and Claude-v1 +25%, but GPT-3.5 did not favor itself. The authors say the data "cannot determine" whether this is a true self-enhancement bias. — [arXiv 2306.05685](https://arxiv.org/abs/2306.05685)
- Zheng et al., overall: GPT-4 as judge agrees with humans over 80% of the time, the same as human-human agreement. — [arXiv 2306.05685](https://arxiv.org/abs/2306.05685)
- "One Token to Fool LLM-as-a-Judge" (2025, NeurIPS 2025): "master key" inputs such as punctuation-only answers or "Thought process:" openers produce false-positive rates up to 80-90%. GPT-4o was fooled up to 35% of the time by punctuation alone. One specialized verifier had a 66.8% false-positive rate on a math set given a blank space. — [arXiv 2507.08794](https://arxiv.org/pdf/2507.08794) (figures as reported in search summaries of the paper)
- Huang et al. 2023 (ICLR 2024): without external feedback, intrinsic self-correction does not help reasoning and often degrades it. Gains attributed to multi-agent debate came from self-consistency aggregation (debate 83.0% vs self-consistency 88.2% at 9 responses). — [arXiv 2310.01798](https://arxiv.org/abs/2310.01798)

### Inferences
- An instruction like "check your own summary" in the same prompt, or a second call to the same model on its own output, is the setup most exposed to self-preference and to intrinsic self-correction failure. A different-family checker, or an NLI-style checker that sees only source plus claim, avoids both.
- Position and verbosity bias argue for a pointwise check (one claim against its source span, yes/no) rather than comparing two outputs.
- Giving the judge the source passage, the analogue of the "reference" in Zheng's math test, cut false approvals from 14/20 to 3/20. A verifier must always be shown the source text, never the claim alone.

### Gaps
- No study I found measures self-preference specifically for DeepSeek flash-class models, or for faithfulness checking as opposed to preference ranking.

## Q4. Rough cost of one extra short verification call per claim (DeepSeek pricing)

### Takeaway
At current DeepSeek flash pricing, a verification call costs a fraction of a US cent. A few claims a day comes to well under $1 a month. Cost is not the constraint; accuracy and the extra failure surface are.

### Cited Findings
- DeepSeek official pricing page (fetched 2026-10-17), as the fetch tool reported it. It lists `deepseek-flash` (DeepSeek-V4.1-Flash) and notes the legacy names `deepseek-v4-flash` / `deepseek-v4-flash-vision-exp` "are still accepted, but the corresponding models have been retired". Prices per 1M tokens:

  | Model | Input, cache hit | Input, cache miss | Output |
  |---|---|---|---|
  | deepseek-flash | $0.003 off-peak / $0.006 peak | $0.15 / $0.30 | $0.60 / $1.20 |
  | deepseek-v4-pro | $0.022 / $0.044 | $0.66 / $1.32 | $1.98 / $3.96 |

  Peak hours are 01:00-04:00 and 06:00-10:00 UTC, Mon-Fri; off-peak is 50% off. Context is 1M tokens. Flash has thinking mode on by default. — [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing)
- Conflicting third-party figure: $0.14 per 1M input and $0.28 per 1M output for "V4 Flash". — [Puter pricing tutorial, Jun 2026](https://developer.puter.com/tutorials/deepseek-api-pricing/). Prefer the official page. Prices have evidently changed between model versions.
- For reference, MiniCheck-FT5 ran 13K checks for $0.24 against GPT-4's $107. — [MiniCheck](https://arxiv.org/html/2404.10774v2)

### Inferences
These are worked examples on the official peak prices above, not sourced figures.
- One check with about 1,500 input tokens (claim plus source span) and about 100 output tokens costs 1,500 × $0.30/M + 100 × $1.20/M ≈ $0.00057, or about $0.0003 off-peak.
- At 5 claims/day (about 150/month) that is about $0.09/month. With a full 4,000-token article as input, it is about $0.0013 per call, or $0.20/month.
- If thinking mode stays on (the flash default), output could reach 500-2,000 reasoning tokens, adding up to about $0.0024 per call. That is still under $0.50/month at this volume, but it adds latency. Disabling thinking matters more for latency than for cost.
- Even at 50 claims/day the check stays at a few dollars a month. That is small against a roughly $100 LLM budget, but the share may matter if the balance is tight.
- A cache hit on a shared system prompt is about 50x cheaper than a miss, so put the fixed verifier instructions first.

### Gaps
- I found no official latency (time to first token, tokens/s) for deepseek-flash. Measure it locally. Per-call latency will be dominated by thinking tokens if those are left on.
- The OpenAI-compatible reseller in use (SumoPod) may price differently from DeepSeek direct. I did not verify this.

## Q5. Multilingual / Indonesian NLI and faithfulness-checking quality

### Takeaway
Indonesian NLI is solvable but well below human level on hard cases. Numbers, spatial reasoning and temporal reasoning are the weakest categories, which is exactly where news summaries make claims. Cross-lingual NLI-based hallucination metrics lose most of their agreement with humans outside high-resource languages.

### Cited Findings
- IndoNLI (Mahendra et al., EMNLP 2021): about 18K human-written pairs. Accuracy, Dev / Test-LAY / Test-EXPERT:

  | Model | Dev | Test-LAY | Test-EXPERT |
  |---|---|---|---|
  | Human | – | 85.1 | 89.1 |
  | XLM-R | 85.7 | 82.3 | 70.3 |
  | IndoBERT-large | 78.7 | 77.1 | 61.5 |
  | mBERT | 76.2 | 72.5 | 57.3 |

  On Test-EXPERT: XLM-R translate-train 75.7, and zero-shot xlm-roberta-large-xnli (no Indonesian training) 73.8. The best model trails humans by 13.4 points on expert data. — [IndoNLI paper](https://aclanthology.org/2021.emnlp-main.821.pdf); [ACL Anthology](https://aclanthology.org/2021.emnlp-main.821)
- IndoNLI diagnostic set, accuracy by phenomenon (IndoBERT-large / XLM-R / translate-train):

  | Phenomenon | IndoBERT-large | XLM-R | Translate-train |
  |---|---|---|---|
  | Numerical & math reasoning | 45.0 | 58.3 | 65.0 |
  | Spatial reasoning | 45.9 | 57.7 | 68.5 |
  | Temporal reasoning | 56.4 | 68.1 | 69.6 |
  | Comparative/superlative | 59.5 | 64.1 | 59.5 |
  | Negation | 71.1 | 71.6 | 79.1 |
  | Morphological derivation | 69.4 | 79.2 | 84.4 |

  — [IndoNLI paper, Table 11](https://aclanthology.org/2021.emnlp-main.821.pdf)
- IndoNLI: in the lay data, contradiction labels lean on negation words (*bukan*, *tidak*). These annotation artifacts are reduced in the expert data. — [IndoNLI paper](https://aclanthology.org/2021.emnlp-main.821.pdf)
- Kang et al. 2024, "Comparing Hallucination Detection Metrics for Multilingual Generation", 19 languages including Indonesian, with an XLM-R-large XNLI checker. NLI-human correlation is 0.35-0.56 in high-resource languages (English 0.49, Chinese 0.35). In lower-resource languages, correlations are "often in the range of 0.00 to 0.30 and not statistically significant". NLI metrics also "encounter significant challenges in accurately verifying the factuality of simple atomic facts". ROUGE and named-entity overlap agree poorly with humans. — [arXiv 2402.10496](https://arxiv.org/html/2402.10496v1)

### Inferences
- A per-claim NLI check on Indonesian news is weakest on the claim types that matter most: amounts, percentages, dates and "since/until" spans. Deterministic checks (number and date matching against the source) should carry those, with NLI or LLM judgment used for relational or causal claims.
- Checking a single short atomic claim (Kang et al.) is harder for NLI than checking a sentence in context. Pass the claim with its source sentence(s), not a decontextualized fact.
- Translating to English before running an English-only checker (MiniCheck, HHEM) is plausible: translate-train beat native training on IndoNLI expert data. But this is untested for faithfulness checkers and adds a translation-error channel.

### Gaps
- No LLM-AggreFact-style faithfulness benchmark exists for Indonesian. No 2025-2026 result was found for LLM judges (DeepSeek, GPT-4o-mini, Gemini Flash) on IndoNLI or on Indonesian summary faithfulness.
- Kang et al. does not give a separate Indonesian correlation figure in the parts read. Indonesian's tier (high or low resource) in their split was not confirmed.
