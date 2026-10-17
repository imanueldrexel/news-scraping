# Citation- and quote-grounded generation: requiring the exact supporting span, and checking it mechanically

Scope note: the focus is grounding claims in a provided source text (RAG / summarization). Two sources below are outside that scope and are flagged where used: Weller et al. ("According to...") grounds to pre-training memory, not a provided document, and the Tow Center study is open-web attribution.

## Q1. ALCE (Gao et al., 2023): citation recall/precision, and how often cited passages do not support the claim

### Takeaway
Even with the passages in context and an explicit instruction to cite, strong 2023 models had about 25% of statements not fully supported by their citations on factoid long-form QA (ASQA), and about 50% on explanatory long-form QA (ELI5). Citations added after the fact (POSTCITE) are far worse than citations produced during generation. An NLI checker (TRUE, T5-11B) agrees with humans well enough to rank systems and to rerank samples.

### Cited Findings
- Setup: the output is split into sentences ("statements"), each citing up to 3 passages. **Citation recall** = 1 if the concatenation of the cited passages *entails* the statement (NLI model TRUE, a T5-11B, premise = cited passages, hypothesis = statement). **Citation precision** flags an "irrelevant" citation: one that does not support the claim on its own *and* whose removal leaves the other citations still supporting it. If recall = 0, precision = 0. — [Gao et al. 2023, ALCE, arXiv:2305.14627](https://arxiv.org/abs/2305.14627)
- Headline: "on the ELI5 dataset, even the best models lack complete citation support 50% of the time". The intro adds: "around 50% generations of our ChatGPT and GPT-4 baselines are not fully supported by the cited passages." — [ALCE](https://arxiv.org/abs/2305.14627)
- ASQA (Table 4; columns MAUVE / EM recall / citation recall / citation precision):
  - ChatGPT VANILLA (5 passages): 66.6 / 40.4 / **73.6 / 72.5**
  - ChatGPT + RERANK (sample 4, keep the one with the best automatic citation recall): 77.0 / 40.2 / **84.8 / 81.6**
  - ChatGPT SUMM (10 passages): citation 68.9 / 61.8
  - ChatGPT SNIPPET: 65.3 / 57.4
  - INLINESEARCH: 58.3 / 58.2
  - CLOSEDBOOK + POSTCITE: **26.7 / 26.7**
  - GPT-4, 5 passages: 68.5 / 75.6; GPT-4, 20 passages: 73.0 / 76.5
  - LLaMA-13B: 10.6 / 15.4

  — [ALCE](https://arxiv.org/abs/2305.14627)
- QAMPARI (Table 5): citation recall and precision are only about 20–28 for every model (ChatGPT VANILLA 20.5 / 20.9; GPT-4 20-passage 27.4 / 28.5; CLOSEDBOOK + POSTCITE 10.0 / 10.0). — [ALCE](https://arxiv.org/abs/2305.14627)
- ELI5 (Table 6): ChatGPT VANILLA citation recall 51.1, precision 50.0; GPT-4 (5 passages) about 44.0 / 50.1. (The PDF-extracted table is misaligned for the other rows, so only these rows are reported.) — [ALCE](https://arxiv.org/abs/2305.14627)
- Post-hoc citation fails: "citation recall of CLOSEDBOOK+POSTCITE is lower than VANILLA by 47% on ASQA". The closed-book model "often generates texts that are correct but not similar to any retrieved passages, making it difficult to match a citation post-hoc." — [ALCE](https://arxiv.org/abs/2305.14627)
- Summaries and snippets raise correctness but lower citation quality "due to the lossy compression". — [ALCE](https://arxiv.org/abs/2305.14627)
- Human vs automatic (NLI) citation judgement:
  - ASQA, ChatGPT VANILLA: human recall/precision 74.7 / 76.6 vs ALCE 75.3 / 74.4.
  - ELI5, ChatGPT VANILLA: human 50.8 / 52.4 vs ALCE 52.8 / 50.4.
  - Agreement: Cohen's kappa 0.698 for recall (substantial) and 0.525 for precision (moderate).
  - Accuracy against human labels: 85.1% for recall, 77.6% for precision.
  - RERANK's automatic scores overstate the human gain, because it optimizes the metric. ASQA: human 79.3 / 81.9 vs ALCE 83.9 / 80.8.

  — [ALCE](https://arxiv.org/abs/2305.14627)

### Inferences
- In-prompt "cite your source" instructions on their own leave roughly 1 in 4 (factoid) to 1 in 2 (explanatory/synthesis) statements without full support. Synthesis-style claims, such as a causal "X because Y", resemble ELI5 more than ASQA, so expect the worse end.
- Sampling several candidates and keeping the one that best passes an NLI citation check (RERANK) gave the largest single gain, about +11 recall and +9 precision on ASQA. Generate-then-verify-and-select is cheap and effective.
- Citing after the fact is a bad design. The quote/citation should be produced together with the claim.

### Gaps
- ALCE does not report a breakdown of *why* unsupported citations fail: wrong passage, partial support, or over-claiming.

## Q2. "Quote then answer" / extract-quotes-first prompting, and "According to..." prompting: measured effects

### Takeaway
Vendor guidance (Anthropic) recommends extracting verbatim quotes first and retracting any claim without a quote, but publishes no numbers for it. The only controlled evidence for "according to" prompting concerns quoting from pre-training memory, and the gains are modest. The strongest recent quantitative evidence is that asking for verbatim evidence makes strong models produce exact substrings 83–93% of the time, with mixed effects on task accuracy.

### Cited Findings
- Anthropic "Reduce hallucinations" guidance:
  - "For tasks involving long documents (>20k tokens), ask Claude to extract word-for-word quotes first before performing its task. This grounds its responses in the actual text, reducing hallucinations."
  - Example prompt: "If you can't find relevant quotes, state 'No relevant quotes found.'"
  - "Verify with citations": "have Claude verify each claim by finding a supporting quote after it generates a response. If it can't find a quote, it must retract the claim." Example: "remove that claim ... and mark where it was removed with empty [] brackets."
  - Caveat in the guide: "these techniques significantly reduce hallucinations, they don't eliminate them entirely."
  - No quantitative evaluation is given.

  — [Anthropic docs, Reduce hallucinations](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations)
- Anthropic Citations API (structured, not prompt-based):
  - "citations are guaranteed to contain valid pointers to the provided documents", because the API "extracts `cited_text` directly".
  - "In Anthropic's evaluations, the citations feature is significantly more likely to cite the most relevant quotes from documents than purely prompt-based approaches." No numbers are published.
  - Plain text and PDF are chunked into sentences, which is the minimum citation granularity.
  - `cited_text` does not count toward output tokens.

  — [Anthropic docs, Citations](https://platform.claude.com/docs/en/build-with-claude/citations)
- "According to..." prompting (Weller et al., 2023/2024; **closed-book, grounding to pre-training corpora, not a provided source**):
  - QUIP-Score is the character n-gram precision (25-character grams, via a Bloom-filter "Data Portrait") of the output against the corpus.
  - Across human-authored grounding prompts, "we can increase the amount of overlap with the chosen corpora by 5-105% while maintaining or even improving the downstream performance". Example: "up to a 6% improvement on NQ".
  - On SARA (tax law, ChatGPT), QUIP went 4.4 → 13.3 (+8.9) and EM 52.0 → 55.0.
  - Anti-grounding prompts lower QUIP. The effect grows with model size.

  — [Weller et al., "According to ...": Prompting Language Models Improves Quoting from Pre-Training Data, arXiv:2305.13252](https://arxiv.org/abs/2305.13252)
- Verbatim-evidence requirement, controlled study (medRxiv 2026, "Show Your Work"):
  - Task: oncology RCT abstracts classified by eligibility scope. Models: GPT-5.2, Gemini 3 Flash, Claude Opus 4.5; 200 trials × 3 runs.
  - Quotes were checked by strict substring match after normalisation (collapse whitespace, trim, strip quotation marks).
  - Mechanically valid quotes: 83.3% (GPT-5.2), 91.2% (Gemini), 91.2% (Claude).
  - The evidence requirement "modestly reduced coverage through increased abstentions and invalid outputs".
  - Conditional macro-F1: GPT-5.2 0.910 → 0.916; Gemini 0.933 → 0.945; Claude 0.828 → 0.777 (p = 0.009).

  — [Show Your Work: Verbatim Evidence Requirements..., medRxiv 2026](https://www.medrxiv.org/content/10.64898/2026.03.03.26346690v1.full)

### Inferences
- The "extract quotes first, retract unquoted claims" pattern is industry best practice, but I found no published A/B number for its effect on hallucination rate in a provided-document setting. Treat any claimed effect size as unmeasured.
- Requiring verbatim evidence is not free. It can raise abstention and, for some models, lower task accuracy (Claude −0.05 F1 in one study). Measure it on your own task.

### Gaps
- No primary quantitative study of Anthropic's quote-first technique was found, and none for OpenAI's equivalent guidance (OpenAI docs were not checked within this budget).
- No study was found measuring "extract quotes first then answer" vs "answer directly" on a summarization or RAG hallucination benchmark with the same model.

## Q3. AIS (Rashkin et al.) and "Evaluating Verifiability in Generative Search Engines" (Liu et al., 2023): fraction of statements fully supported

### Takeaway
In commercial generative search engines (2023), only about half of the generated sentences were fully supported by their citations, and about a quarter of the citations did not support the sentence they were attached to. AIS defines "supported" as what a generic hearer would accept as "according to source P, s".

### Cited Findings
- Across Bing Chat, NeevaAI, Perplexity.ai and YouChat: "a mere 51.5% of generated sentences are fully supported by citations" (citation recall) and "only 74.5% of citations support their associated sentence" (citation precision). Responses "are fluent and appear informative, but frequently contain unsupported statements and inaccurate citations." — [Liu, Zhang, Liang 2023, Evaluating Verifiability in Generative Search Engines, arXiv:2304.09848](https://arxiv.org/abs/2304.09848)
- AIS ("Attributable to Identified Sources") is "a new evaluation framework for assessing the output of natural language generation models, when such output pertains to the external world". It uses a two-stage human annotation pipeline and is validated on conversational QA, summarization and table-to-text. — [Rashkin et al., Measuring Attribution in Natural Language Generation Models, arXiv:2112.12870](https://arxiv.org/abs/2112.12870)
- RARR defines automatic AIS as `Attr_auto(y, A) = avg over sentences s of max over evidence e of NLI(e, s)`. Human AIS on PaLM outputs before any editing is only 35.4% (NQ), 24.5% (StrategyQA) and 13.2% (LaMDA on QReCC). — [Gao et al. 2022, RARR, arXiv:2210.08726](https://arxiv.org/abs/2210.08726)
- Attribution checkers are themselves imperfect. On AttributionBench, "even a fine-tuned GPT-3.5 only achieves around 80% macro-F1" on binary "is the claim supported by the evidence". The main error sources are insensitivity to "nuanced information" and a mismatch between what the model and the annotators see. — [Li et al. 2024, AttributionBench, arXiv:2402.15089](https://arxiv.org/abs/2402.15089)
- Even with mandatory verbatim excerpts attached to every claim (veterinary RAG, 6 frontier/open models, 4,986 claims), "the annotators judge almost half of the claims as unverified by the provided excerpts". Some open-weight judge models were "too lenient, judging only around 20% of claims as unverified." — [Kartáč et al. 2026, VetScore, arXiv:2608.03675](https://arxiv.org/abs/2608.03675)

### Inferences
- Across very different systems (2023 search engines, 2023 RAG prompting, 2026 excerpt-cited RAG), the share of claims actually supported by their attached evidence stays around 50–75%. Attaching evidence does not by itself make claims supported.
- An LLM- or NLI-based support check catches many failures but is roughly 80–85% accurate against humans and tends to be lenient. It is a filter, not proof.

### Gaps
- Bohnet et al. 2022 (Attributed QA) numbers were not retrieved; only the abstract was available within budget.
- AIS per-task attribution rates and inter-annotator agreement were not retrieved from the full text.

## Q4. A real quote that does not support the claim; quote fabrication rates; verifying quotes by string match

### Takeaway
Fabricated quotes are a minority failure for frontier models when the source is in context: about 5–20% of quotes fail exact match, and most of those are formatting or paraphrase rather than invention. The larger failure is a real, exactly matching quote that does not support the claim. Substring checks pass 83–93% of quotes, but semantic checks find only 48–79% of evidence-bearing outputs supported, and humans find about half of excerpt-backed claims unverified. Citations can also be "correct but unfaithful" (post-rationalized) in up to 57% of cases.

### Cited Findings
- **Exact-match rate of model-supplied excerpts against the cited source** (VetScore, 2026; 6 models; 67 queries; about 31.5 excerpts per output; mean excerpt length 128 characters).
  - Exact match on the cited lines: Gemini 3.1 Pro 93.3%, Claude Opus 4.6 88.5%, Qwen3.5-397B 84.4%, GPT-5.4 80.2%, DeepSeek V3.2 71.4%, Mistral Small 4 41.5%.
  - Exact match anywhere in the cited source: 94.1 / 89.6 / 87.3 / 80.7 / 77.0 / 49.7 respectively.
  - "Fuzzy" match, which allows ellipsis-bridged anchors, lifted GPT-5.4 from 80.2% to 92.6%, because it uses "..." a lot.
  - Adding an LLM classifier that accepts formatting-only differences gave 98.3 / 96.6 / 93.8 / 96.5 / 91.0 / 62.1%. Also accepting faithful paraphrases gave 99.8 / 99.7 / 98.3 / 99.3 / 98.1 / 85.5%.
  - So "most unmatched excerpts contain either formatting differences or are faithful paraphrases". The exception is Mistral Small, which paraphrases about 23% and fabricates more than 14% of its excerpts.
  - Non-existent source IDs were at most 2.1%.

  — [VetScore, arXiv:2608.03675](https://arxiv.org/abs/2608.03675)
- **Correct quote, wrong relation, quantified** (medRxiv 2026):
  - 83.3–91.2% of runs produced mechanically valid (exact-substring) quotes.
  - Yet "only 48.0% to 78.8% of evidence-bearing predictions were rated supported" by a second-LLM judge that saw only the label and the quote. Per model: GPT-5.2 73.8–78.8%, Claude 67.2–73.5%, Gemini 48.0–59.0%.
  - Mechanically valid quotes sometimes failed semantic review: the quote was in the source but did not justify the assigned label.

  — [Show Your Work, medRxiv 2026](https://www.medrxiv.org/content/10.64898/2026.03.03.26346690v1.full)
- **Valid excerpts do not make claims faithful**:
  - "Citation excerpts can be used to increase the reliability of generated outputs ... However, this does not guarantee that generated claims are faithful to the provided excerpts."
  - Humans judged almost half of the claims unverified, even though nearly all excerpts were genuine or faithful paraphrases (previous bullet).
  - Their Figure 1 shows the mechanism. A genuine excerpt ("Fluticasone provided good tolerability and efficacy ... without side effects") is attached to a claim decomposed into 3 atomic claims; one ("the study was conducted in 2021") is not supported (raw score 0.67).

  — [VetScore, arXiv:2608.03675](https://arxiv.org/abs/2608.03675)
- **Correct is not faithful**: citations can be correct (the document supports the statement) without the model having relied on it (post-rationalization). "Up to 57 percent of the citations" lack faithfulness. — [Wallat, Heuss, de Rijke, Anand 2024, Correctness is not Faithfulness in RAG Attributions, arXiv:2412.18004](https://arxiv.org/abs/2412.18004)
- **Irrelevant citations are common in ALCE**: citation precision of 72.5% (ChatGPT ASQA) means about 27% of citations are irrelevant or attached to unsupported statements. On ELI5 it is about 50%. — [ALCE](https://arxiv.org/abs/2305.14627)
- **Misattribution without a provided source** (out of scope, open web): the Tow Center gave ChatGPT 200 quotes from 20 publishers and asked it to identify the source. It gave "partially or entirely incorrect responses on a hundred and fifty-three occasions", acknowledging inability only 7 times. — [MediaPost report of the Tow Center/CJR study, 2024](https://www.mediapost.com/publications/article/401521/chatgpt-misattributes-article-sources-study-finds.html) (secondary report; primary CJR article not fetched)

### Inferences
- A mechanical substring check (after normalising whitespace and quote characters, and allowing "..." splits) is cheap and catches the fabricated-quote class. For frontier models with the source in context, that class is small: under about 5% after allowing formatting. The check also turns a soft hallucination into a hard, detectable failure. Strict exact match will falsely reject 5–20% of honest quotes unless normalisation and ellipsis handling are added (GPT-5.4: 80% exact vs 93% fuzzy).
- The substring check cannot catch the dominant failure: a real quote that does not entail the claim, especially over-reach such as an extra date, an extra causal link or a stronger verb. That gap is about 12–43 points in the medRxiv study and about 50% of claims in VetScore. An entailment or support check per claim (or per atomic sub-claim) is required on top of the substring check.
- For causal claims specifically ("X because Y"), the quote may establish X and Y separately while the source never states the link. Only an entailment check against the full claim, or a requirement that the quote itself contains the causal connective, addresses this. This is extrapolated; no paper measured causal claims specifically.

### Gaps
- No study found that isolates causal-relation claims ("because", "due to", "led to") and measures how often a genuine quote fails to support the causal link.
- No published false-negative rate for normalised substring matching on non-English (e.g. Indonesian) text was found.

## Q5. Generation-with-quotes plus a verification step (RARR, Self-RAG, reranking, structured citations): results

### Takeaway
Adding a verification or critique step reliably raises attribution:
- ALCE RERANK: +11 citation recall.
- Self-RAG's learned critique tokens: from about 2–7 to about 67–71 citation precision/recall for 7–13B models.
- RARR post-hoc editing: +8 human AIS points while preserving about 90% of intent.

Absolute support still tops out around 70–85%, and post-hoc attribution of unconstrained text is weaker than constrained generation.

### Cited Findings
- **RARR** (Retrofit Attribution using Research and Revision) researches evidence for each claim, then edits unsupported content (PaLM outputs; AIS before → after):

  | Data | auto-AIS | human AIS | intent preservation | F1AP |
  |---|---|---|---|---|
  | NQ | 45.6 → 54.9 | 35.4 → 43.4 | 90.0% | 57.0 |
  | StrategyQA | 37.6 → 45.1 | 24.5 → 31.5 | 92.6% | — |
  | QReCC (LaMDA outputs) | 18.8 → 29.4 | 13.2 → 28.3 | 95.6% | — |

  - Baseline EFEC reaches higher AIS (NQ 35.4 → 48.3) but preserves intent only 16.0% (F1AP 17.1), because it rewrites the passage.
  - The authors note attribution "does not entail correctness".

  — [Gao et al. 2022, RARR, arXiv:2210.08726](https://arxiv.org/abs/2210.08726)
- **Self-RAG** (reflection/critique tokens incl. ISSUP "is supported"), ALCE-ASQA citation precision / recall:
  - Self-RAG 7B: 66.9 / 67.8
  - Self-RAG 13B: 70.3 / 71.3
  - Retrieval-augmented ChatGPT: 65.1 / 76.6
  - Retrieval-augmented Alpaca/Llama2 7–13B baselines: about 2.0–5.5 precision and 3.6–7.5 recall
  - Self-RAG "even outperform[s] ChatGPT in citation precision".
  - Raising the weight of the ISSUP critique score at decoding increases citation precision, a precision/fluency trade-off.
  - Removing ISSUP from beam search "hurts performance on ASQA".
  - Row labels in the extracted table are partly misaligned. The Self-RAG rows are certain; the baseline row assignment is a best reading.

  — [Asai et al. 2023, Self-RAG, arXiv:2310.11511](https://arxiv.org/abs/2310.11511)
- **ALCE RERANK** (sample 4 and pick by NLI citation recall): ChatGPT ASQA citation recall 73.6 → 84.8 and precision 72.5 → 81.6. Human-validated: 74.7 → 79.3 and 76.6 → 81.9. On ELI5 human recall went 50.8 → 59.7. — [ALCE](https://arxiv.org/abs/2305.14627)
- **Post-hoc citation alone** (CLOSEDBOOK + POSTCITE) gives ASQA citation recall 26.7 vs 73.6 for in-context generation with citations. — [ALCE](https://arxiv.org/abs/2305.14627)
- **Anthropic's self-verify-and-retract pattern** ("find a direct quote ... If you can't find a supporting quote for a claim, remove that claim") is recommended, with no published numbers. — [Anthropic docs](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations)
- **Structured citations** (Anthropic Citations API) guarantee that the cited span exists in the document, which removes the fabricated-quote class by construction. They do not guarantee that the span supports the claim. — [Anthropic docs, Citations](https://platform.claude.com/docs/en/build-with-claude/citations)
- **Decompose-then-verify with an LLM judge** (VetScore): claims are split into atomic claims and each is judged against the excerpts. With strong judges it correlates highly with expert veterinarians. Weak open-weight judges are too lenient (about 20% unverified vs nearly 50% for humans), and human inter-annotator agreement on support is only α = 0.623. — [VetScore, arXiv:2608.03675](https://arxiv.org/abs/2608.03675)

### Inferences
- The evidence supports a layered design:
  1. Generate each claim with an attached verbatim quote, in-generation rather than post-hoc.
  2. Check the quote mechanically with a normalised substring match; reject it or retry.
  3. Run an entailment/support check of claim vs quote, ideally on atomic sub-claims, with a strong judge.
  4. Drop or rewrite claims that fail, or resample (RERANK-style best-of-N).
- Each layer catches a different failure class: fabrication, wrong relation or over-reach, and residual error.
- Expect the support judge itself to be about 80–85% accurate and lenient-biased. Weaker or cheaper judges are measurably more lenient.

### Gaps
- No head-to-head study was found comparing, on the same RAG/summarization task, (a) quote requirement only, (b) quote plus substring check, and (c) quote plus substring check plus NLI. Per-layer marginal catch rates have to be stitched together from different papers.
- Attribution-aware fine-tuning beyond Self-RAG (e.g. LongCite, FRONT, Trust-Align) was not covered within the tool budget.
