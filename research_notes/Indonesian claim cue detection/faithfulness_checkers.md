# Automatic faithfulness / factual-consistency checkers for LLM summaries (as a complement to a lexical fact gate for Indonesian story arcs)

Scope note: almost every benchmark number below is **English-only** unless marked otherwise. The only Indonesian-language numbers found are IndoNLI (sentence-pair NLI, not summary factuality) and mFACE's XLSum-Indonesian NLI score (a model score, not a validated accuracy).

## 1. Accuracy of SummaC, AlignScore, QAFactEval, FactCC, MiniCheck and LLM judges on the benchmarks

### Takeaway
On the current reference benchmark (LLM-AggreFact, 11 English datasets, balanced accuracy), the best small checkers (Bespoke-MiniCheck-7B 77.4, FactCG-DeBERTa-L 0.4B 75.6, MiniCheck-Flan-T5-L 0.8B 75.0) match or beat frontier LLM judges (Claude-3.5 Sonnet 77.2, GPT-4o 75.9, GPT-4 75.3), while older checkers trail by 5-13 points (AlignScore 70.4, SummaC-ZS 67.9, QAFactEval 66.5, SummaC-CV 62.1). Everything tops out in the mid-to-high 70s, so roughly one decision in four is wrong even for the best checker.

### Cited Findings
- LLM-AggreFact leaderboard (balanced accuracy, average over 11 datasets: CNN, XSum, MediaS, MeetB, WiCE, REVEAL, ClaimVerify, FactCheck, ExpertQA, LFQA, RAGTruth): Bespoke-MiniCheck-7B 77.4; Claude-3.5 Sonnet 77.2; Granite Guardian 3.3 (8B) 76.5; Mistral-Large 2 (123B) 76.5; gpt-4o-2024-05-13 75.9; FactCG-DeBERTa-L (0.4B) 75.6; Qwen2.5-72B-Instruct 75.6; MiniCheck-Flan-T5-L (0.8B) 75.0; Llama-3.3-70B 74.5; Llama-3.1-405B 74.4; QwQ-32B-Preview 71.8. English only. — [LLM-AggreFact leaderboard](https://llm-aggrefact.github.io/)
- MiniCheck paper (Tang, Laban, Durrett, EMNLP 2024), LLM-AggreFact balanced accuracy: MiniCheck-FT5 74.7, MiniCheck-DBTA 72.6, MiniCheck-RBTA 72.7; GPT-4 75.3; Claude-3 Opus 74.1; Gemini-Pro 66.2; AlignScore 70.4; SummaC-ZS 67.9; QAFactEval 66.5; SummaC-CV 62.1; T5-NLI-Mixed 61.0. The authors state all data is English and name the lack of multilingual benchmarks as a limitation. — [MiniCheck, arXiv 2404.10774](https://arxiv.org/html/2404.10774v2); [ACL Anthology EMNLP 2024](https://aclanthology.org/2024.emnlp-main.499)
- SummaC (Laban et al., TACL 2022), SummaC benchmark (6 datasets: CoGenSumm, XSumFaith, Polytope, FactCC, SummEval, FRANK), balanced accuracy: SummaC-Conv 74.4 ("a 5% point improvement compared to prior work"); SummaC-ZS 72.1. — [SummaC, arXiv 2111.09525](https://arxiv.org/abs/2111.09525); per-dataset figures (ZS: CGS 70.4, XSF 58.4, Polytope 62.0, FactCC 83.8, SummEval 78.7, FRANK 79.0; Conv: 64.7/66.4/62.7/89.5/81.7/81.6) via search snippet of the same paper, [TACL](https://preview.aclanthology.org/setup/2022.tacl-1.10)
- AlignScore (Zha et al., ACL 2023): RoBERTa-large, 355M parameters, trained on 4.7M examples from 7 task types (NLI, QA, paraphrase, fact verification, IR, semantic similarity, summarization); "matches or even outperforms metrics based on ChatGPT and GPT-4 that are orders of magnitude larger". — [AlignScore, arXiv 2305.16739](https://arxiv.org/abs/2305.16739)
- AlignScore paper, SummaC benchmark **AUC-ROC** (Table 2) averages: AlignScore-large 88.6, AlignScore-base 87.4, UniEval 84.6, QAFactEval 83.8, CTC 81.2, SummaC-Conv 81.0, SummaC-ZS 79.0, FactCC 68.8, DAE 66.8, plain MNLI 47.9. XSumFaith (the most abstractive set) is hardest for everyone: AlignScore-large 75.8, SummaC-ZS 58.0, QAFactEval 66.1, FactCC 55.1. — [AlignScore PDF, Table 2](https://arxiv.org/pdf/2305.16739)
- Same paper, SummaC benchmark **balanced accuracy** (appendix Table 9) averages: AlignScore-large 82.0, AlignScore-base 80.6, UniEval 78.1, SummaC-Conv 75.0, SummaC-ZS 73.4, FactCC 68.8, DAE 66.8, QAFactEval 62.6 (note: QAFactEval scores much lower on balanced accuracy than on AUC in this re-run, 62.6 vs 83.8; the QAFactEval paper itself reports a stronger SummaC result, so threshold choice matters). — [AlignScore PDF, Table 9](https://arxiv.org/pdf/2305.16739); [QAFactEval, arXiv 2112.08542](https://arxiv.org/pdf/2112.08542)
- TRUE benchmark (11 datasets) AUC-ROC averages in the AlignScore paper: AlignScore-large 87.4, AlignScore-base 86.3, SummaC-Conv 82.5, SummaC-ZS 82.2, QAFactEval 80.1, UniEval 79.5, FactCC 60.8. — [AlignScore PDF, Table 3](https://arxiv.org/pdf/2305.16739)
- LLM metrics vs AlignScore (Spearman on SummEval / QAGS-XSum / QAGS-CNNDM): G-Eval-4 (GPT-4) 50.7 / 53.7 / 68.5; AlignScore-large 46.6 / 57.2 / 73.9; ChatGPT 43.3 on SummEval. — [AlignScore PDF, Table 5](https://arxiv.org/pdf/2305.16739)
- SummEdits (Laban et al. 2023, "LLMs as factual reasoners"): most LLMs perform close to random chance; GPT-4, the best, is still 8% below estimated human performance; inter-annotator agreement about 0.9. — [SummEdits, arXiv 2305.14540](https://arxiv.org/abs/2305.14540)
- FRANK (Pagnoni et al., NAACL 2021): "all metrics exhibit low correlations with human judgements"; best partial Pearson/Spearman: BERTScore-P 0.27/0.35, FactCC 0.20/0.30, DAE 0.16/0.14. — [FRANK, ar5iv 2104.13346](https://ar5iv.labs.arxiv.org/html/2104.13346)

### Inferences
- A frontier LLM judge buys almost nothing in accuracy over a 0.4-0.8B specialised checker on English, at a large cost premium (section 4). DeepSeek is not on the leaderboard excerpt fetched; Qwen2.5-72B (75.6) and Llama-3.3-70B (74.5) suggest open models of that class sit 1-3 points below Claude/GPT-4o.
- ~75% balanced accuracy means a checker used as a hard refusal gate will both pass some fabrications and refuse some faithful summaries; it is a second signal, not a replacement for a deterministic gate.

### Gaps
- No leaderboard number found for DeepSeek models (V3/R1) as factuality judges.
- Original AggreFact (Tang et al. 2023) and TRUE (Honovich et al. 2022) numbers were not fetched directly; the TRUE figures above are the AlignScore paper's re-run.

## 2. Multilingual / Indonesian support and degradation on non-English text

### Takeaway
There is no Indonesian summary-factuality benchmark and no Indonesian-trained faithfulness checker in the literature found. The usable building blocks are multilingual NLI models (XNLI-trained XLM-R / mDeBERTa / mT5) and IndoNLI. On IndoNLI's hard expert test set, the best models reach 70-76% accuracy vs 89% human; numerical (58-65%), temporal (68-70%) and spatial reasoning are the weakest categories, which are exactly the "end date / schedule" details the arc gate cares about. A 2024 multilingual study found NLI-based hallucination metrics fail on lower-resource languages and on single-fact hallucinations.

### Cited Findings
- IndoNLI (Mahendra et al., EMNLP 2021): ~18K human-elicited Indonesian premise-hypothesis pairs; expert-annotated data used only as a test set, built to include numerical reasoning, structural changes, idioms, temporal and spatial reasoning. — [IndoNLI, ACL Anthology](https://aclweb.org/anthology/2021.emnlp-main.821.pdf); [arXiv 2110.14566](https://arxiv.org/abs/2110.14566v1)
- IndoNLI accuracy (Dev / Test_lay / Test_expert, mean of 3 runs): Human – / 85.1 / 89.1; XLM-R 85.7 / 82.3 / 70.3; IndoBERT-large 78.7 / 77.1 / 61.5; IndoBERT-lite 76.2 / 74.1 / 58.9; mBERT 76.2 / 72.5 / 57.3; CBoW 54.7 / 50.1 / 36.9. — [IndoNLI Table 6](https://aclweb.org/anthology/2021.emnlp-main.821.pdf)
- Cross-lingual transfer on IndoNLI (XLM-R): zero-shot model trained on MNLI+XNLI (`joeddav/xlm-roberta-large-xnli`) 80.8 / 78.3 / **73.8**; translate-train (MNLI machine-translated to Indonesian) 82.8 / 80.4 / **75.7**; trained on IndoNLI itself 85.7 / 82.3 / 70.3. So an off-the-shelf XNLI model scores *higher* on the hard expert set than one trained on IndoNLI data. — [IndoNLI Table 10](https://aclweb.org/anthology/2021.emnlp-main.821.pdf)
- IndoNLI diagnostic set (650 expert pairs), accuracy by phenomenon for IndoBERT-large / XLM-R / XLM-R translate-train: Negation 71.1 / 71.6 / 79.1; Temporal expression & reasoning 56.4 / 68.1 / 69.6; Numerical & math 45.0 / 58.3 / 65.0; Comparative & superlative 59.5 / 64.1 / 59.5; Spatial 45.9 / 57.7 / 68.5; Common-sense 55.6 / 63.8 / 70.2; Coreference 64.8 / 74.3 / 74.8; Lexical semantics 58.4 / 71.3 / 76.9; Morphological derivation 69.4 / 79.2 / 84.4. The paper names NUM and COMP the hardest categories; negation is "decent... more than 70%". — [IndoNLI Table 11](https://aclweb.org/anthology/2021.emnlp-main.821.pdf)
- IndoNLI annotation artefact: in the lay (crowd) data the top-3 PMI words for the contradiction label are all negation words (*bukan*, *tidak*); in the expert data only one is, i.e. crowd-trained models can learn "negation word => contradiction" as a shortcut. — [IndoNLI §5](https://aclweb.org/anthology/2021.emnlp-main.821.pdf)
- mFACE (Aharoni et al., Findings of ACL 2023): prior factual-consistency detectors "focus exclusively on English"; mFACE uses an mT5-XXL NLI model fine-tuned on ANLI (162K English) + XNLI (37K, 15 languages) to filter training data and control generation for summarization in 45 XLSum languages (Indonesian included). XNLI test accuracy averages 90.0 (Urdu 86.3 to English 93.5); on English TRUE it gets ROC AUC 82.4 vs 83.4 for an English-only model; Indonesian XLSum NLI score 79.06 (a model-assigned score, not an accuracy). NLI score correlates with human Attribution ratings at 0.36 (ROUGE 0.15). Models and human judgements released. — [mFACE, arXiv 2212.10622](https://arxiv.org/html/2212.10622v2); [Findings ACL 2023](https://preview.aclanthology.org/fix_video/2023.findings-acl.220.pdf)
- Kang, Blevins, Zettlemoyer (2024), "Comparing Hallucination Detection Metrics for Multilingual Generation": lexical metrics are ineffective, NLI-based metrics perform well and correlate with human annotations in many settings, but "do not detect single-fact hallucinations well and fail for lower-resource languages". — [arXiv 2402.10496](https://arxiv.org/abs/2402.10496)
- Liputan6 (Koto, Lau, Baldwin, AACL 2020): 215,827 Indonesian document-summary pairs from Liputan6.com; includes error analysis of low-ROUGE summaries exposing problems with ROUGE and with the models. — [Liputan6, arXiv 2011.00679](https://arxiv.org/pdf/2011.00679)
- Koto et al. 2021 used Liputan6 in a cross-language study of summarization evaluation metrics (human annotation of focus and coverage in several languages including Indonesian); their FFCI framework defines faithfulness, focus, coverage, inter-sentential coherence. — [Evaluating the Efficacy of Summarization Evaluation across Languages, arXiv 2106.01478](https://arxiv.org/pdf/2106.01478)
- Poly-FEVER (2025): multilingual fact-verification benchmark, 77,973 claims in 11 languages, finds language-specific biases in hallucination detection accuracy (open-world fact verification, not source-grounded summaries). — [Poly-FEVER, arXiv 2503.16541](https://arxiv.org/abs/2503.16541v2)

### Inferences
- Indonesian is a mid-resource language with good XLM-R pretraining coverage, so an XNLI model is usable but should be expected to perform around the IndoNLI expert-set level (~74%) on hard pairs, and worse on numbers/dates (~58-65%), than the English benchmarks suggest.
- Running an English checker (MiniCheck, AlignScore) on machine-translated Indonesian is possible, but translation can itself drop hedges (*diduga*, *disebut-sebut*) or change dates, so it adds a second error source exactly on the cues the gate protects. No measurement of this was found.
- Any NLI checker for this project would need a small Indonesian eval set built from the project's own arc failures (fabricated cause, dropped hedge, invented end date/schedule) before it could be trusted; IndoNLI's diagnostic tags give a template for tagging.

### Gaps
- No Indonesian (or IndoSum/Liputan6) study of summary *factuality* detection accuracy was found; Koto et al.'s cross-language work covers focus/coverage, and whether it measured Indonesian faithfulness was not confirmed.
- Whether Kang et al. 2024 includes Indonesian, and their per-language numbers, was not retrieved (only the abstract was read).
- No published Indonesian results for mDeBERTa-XNLI or for MiniCheck/AlignScore on translated input.

## 3. Error types: causal links, dropped hedges, negation, dates/end points

### Takeaway
Fine-grained typologies exist (FRANK's seven categories), and they show that the error types this project worries about are the ones checkers handle worst: discourse-link (causal/temporal ordering) errors are rare in benchmarks (3% of FRANK errors) and poorly detected, QA-based metrics correlate *negatively* with them, and NLI models are weakest on numbers and temporal reasoning. No benchmark targeting hedge/modality loss (speculation presented as fact) in summaries was found.

### Cited Findings
- FRANK typology (Pagnoni et al., NAACL 2021): Predicate, Entity, Circumstance (time, location, manner), Coreference, Discourse Link (temporal ordering / causal relations between statements), Out-of-Article, Grammatical; grounded in frame semantics and discourse theory; 2,250 annotated CNN/DM and XSum summaries. — [FRANK, ACL Anthology](https://aclanthology.org/2021.naacl-main.383); [ar5iv](https://ar5iv.labs.arxiv.org/html/2104.13346)
- FRANK error distribution: Entity 36%, Out-of-Article 27%, Circumstance 13%, Grammatical 12%, Coreference 10%, Predicate 10%, Discourse Link 3% (only in multi-sentence summaries). — [FRANK](https://ar5iv.labs.arxiv.org/html/2104.13346)
- FRANK metric ablation: entailment metrics (FactCC, DAE) are strongest on semantic-frame errors (predicate, entity, circumstance); DAE has the highest correlation with discourse errors; FactCC struggles with coreference and discourse-link errors; QA metrics (FEQA, QAGS) show *negative* correlation with discourse errors; the authors conclude synthetic training errors "need to go beyond simple pronoun swaps" to capture discourse-level mistakes. — [FRANK](https://ar5iv.labs.arxiv.org/html/2104.13346)
- Negation and dates in Indonesian NLI: negation ~72-79%, temporal 68-70%, numerical 58-65% for XLM-R variants on IndoNLI's expert diagnostic set (see section 2). — [IndoNLI Table 11](https://aclweb.org/anthology/2021.emnlp-main.821.pdf)
- Kang et al. 2024: NLI metrics do not detect single-fact hallucinations well. — [arXiv 2402.10496](https://arxiv.org/abs/2402.10496)
- SummEdits builds minimal edits (e.g. entity changes, negation/antonym edits, inserted facts) to test whether LLMs catch small inconsistencies; most LLMs are near random. — [SummEdits, arXiv 2305.14540](https://arxiv.org/abs/2305.14540) (per-edit-type numbers not retrieved)
- MetaFaith-style work finds LLMs largely fail to make their linguistic uncertainty match their intrinsic uncertainty (about the model's own hedging, not about preserving the source's hedges). — search summary of [arXiv 2505.04847 and related](https://arxiv.org/pdf/2505.04847); low confidence, snippet only

### Inferences
- An invented cause ("X happened because Y") where X and Y are both in the sources is a discourse-link error: each atom is supported, only the relation is not. Sentence- or atom-level NLI that checks facts one at a time is structurally prone to pass it, and FRANK shows metrics are weakest here. This supports keeping the causal check deterministic/lexical (e.g. one-link causal gate) and treating NLI only as a residual check.
- A dropped hedge ("diduga" -> asserted) is formally an entailment *strengthening*: a well-trained 3-way NLI model should mark "X is the cause" as neutral given "X is suspected to be the cause", but no benchmark measures this for summaries, and IndoNLI's shortcut finding (negation words predict contradiction) suggests models key on surface words. Expect unreliable behaviour; must be measured on own data.
- Dates/end points/schedules map to FRANK "Circumstance" errors and IndoNLI NUM/TEMP tags, where multilingual NLI accuracy is lowest; a lexical/structured comparison of date expressions is likely more reliable than NLI for these.

### Gaps
- No benchmark or study was found that isolates hedge/modality loss (speculation stated as fact) as an error type for summarization checkers, in any language.
- DiaSumFact and other error-type benchmarks (e.g. AggreFact's error-type analysis, Tang et al. 2023) were not fetched; per-type detection rates for MiniCheck/LLM judges on causal errors were not found.
- SummEdits per-edit-type accuracies were not retrieved.

## 4. Practical design: claim decomposition, per-claim verification, cost, LLM judge variance, refusal gate with retry

### Takeaway
A specialised checker costs about 1/400th of a GPT-4 judge for the same English accuracy; decomposing claims into atomic facts did not improve accuracy for GPT-4 in MiniCheck's tests and cost 2-4x more. LLM judges are not deterministic even at temperature 0, so a gate built on one needs repeated calls or a margin. No paper was found that evaluates "checker as refusal gate with regeneration" end to end.

### Cited Findings
- Cost: on the 13K-example LLM-AggreFact test set, GPT-4 cost $107 vs $0.24 for MiniCheck-FT5 (">400 times cheaper") at near-equal accuracy. — [MiniCheck](https://arxiv.org/html/2404.10774v2)
- Decomposition: splitting claims into atomic facts "showed near-zero performance change for GPT-4 and mixed changes for specialized fact-checkers", while raising inference cost 2-4x; the authors advise against it without demonstrated gains. MiniCheck's synthetic training data instead teaches the model to check each fact within a sentence-level claim and to recognise synthesis across sentences. — [MiniCheck](https://arxiv.org/html/2404.10774v2)
- FActScore (Min et al., EMNLP 2023): decompose-then-verify; splits a generation into atomic facts and reports the share supported by a knowledge source. — [FActScore, arXiv 2305.14251](https://arxiv.org/html/2305.14251v2)
- SAFE (Wei et al. 2024, Google DeepMind): LLM decomposes into atomic facts and verifies each via search; $0.19 per response vs $4.00 for human annotation (>20x cheaper); 72% agreement with FActScore human labels, and SAFE judged correct in 76% of sampled disagreements. (Open-world, search-grounded, English.) — search summary of [LongFact/SAFE](https://www.emergentmind.com/topics/longfact); [OpenFActScore, arXiv 2507.05965](https://arxiv.org/html/2507.05965v1)
- LLM judge non-determinism: runs are not deterministic at temperature 0; in one study GPT-4 Turbo changed its verdicts in 5.7% of votes, with Mixtral 8x7B the only self-consistent evaluator; batching in inference servers selects different kernels, causing variation. — search snippet, [Safer or Luckier? arXiv 2503.09347](https://arxiv.org/pdf/2503.09347) (attribution to this paper is from the search result, not a full read)
- A 2026 multi-model study (GPT-4o, GPT-4o-mini, Gemini-2.5-Flash, Claude-Haiku-4.5, Claude-Sonnet-4.5, two temperatures) reports "substantial inconsistency across all models, even under temperature=0", and systematic strictness differences between model families. — [Same Input, Different Scores, arXiv 2603.04417](https://arxiv.org/abs/2603.04417)
- Latency/size reference points: AlignScore-large 355M (RoBERTa-large); MiniCheck-FT5 770M; FactCG-DeBERTa-L 0.4B; Bespoke-MiniCheck-7B 7B. — [AlignScore](https://arxiv.org/abs/2305.16739); [MiniCheck](https://arxiv.org/html/2404.10774v2); [LLM-AggreFact](https://llm-aggrefact.github.io/)

### Inferences
- For this pipeline (story arcs summarise many Indonesian articles; the judge would run once per arc sentence against the cited sources), a 0.4-0.8B NLI-style model run locally adds negligible cost, while an LLM judge per sentence multiplies the edition's LLM spend; given the project's ~$100 SumoPod budget, a DeepSeek judge per arc sentence would need costing before adoption.
- Because LLM verdicts vary run to run, an LLM-judge gate is not reproducible in tests or replays the way the current lexical gate is; if used, it should be a soft signal (log + retry once) rather than the sole refusal.
- Per-sentence (not per-atom) checking against the specific cited articles matches MiniCheck's finding and keeps cost low; long multi-article sources need chunking, since the checkers are trained on document-claim pairs of limited length.

### Gaps
- No measured cost/latency for DeepSeek as a factuality judge.
- No published evaluation of "checker-triggered regeneration" (retry rate, final faithfulness) for summarization was found.
- No measurement of MiniCheck/AlignScore latency per claim on CPU was retrieved.

## 5. When to prefer NLI/LLM checkers over lexical rules, and documented hybrid designs

### Takeaway
The literature consistently finds lexical-overlap metrics poor at detecting hallucination in general (Kang et al. 2024; FRANK), and model-based checkers better on average. But the same literature shows model checkers are weakest on the specific, high-stakes cues of this project (causal relations, numbers/dates, single inserted facts, non-English text). No paper was found that documents a "rules for recall-critical cues + NLI for the residual" hybrid for summarization; it is a reasonable design, not an established one.

### Cited Findings
- Lexical hallucination metrics are ineffective across languages; NLI-based metrics perform well in high-resource languages but fail in lower-resource ones and on single-fact hallucinations. — [Kang et al. 2024, arXiv 2402.10496](https://arxiv.org/abs/2402.10496)
- On the SummaC benchmark (AUC), NER-overlap scores 60.4 vs AlignScore-large 88.6 and SummaC-ZS 79.0; ROUGE-2 reaches 78.1, so surface overlap is not useless on easy datasets but collapses on abstractive ones (ROUGE-2 on XSumFaith 65.9). — [AlignScore Table 2](https://arxiv.org/pdf/2305.16739)
- FRANK: QA-based metrics anti-correlate with discourse errors; entailment metrics are best on frame errors; synthetic training data needs to go beyond simple swaps to capture discourse errors. — [FRANK](https://ar5iv.labs.arxiv.org/html/2104.13346)
- mFACE shows a multilingual NLI model used as a *filter* (on training data) and as a control signal improves multilingual summary faithfulness in 45 languages incl. Indonesian, a documented use of NLI as a gate, though on training data rather than at serve time. — [mFACE](https://arxiv.org/html/2212.10622v2)

### Inferences
- Note: a "lexical gate" here means rules over cue words (causal connectives, hedge verbs such as *diduga/disebut*, end-point and schedule phrases) that need a matching cue in the source. That is a different thing from the overlap metrics the literature rejects; the papers above do not test it, so their "lexical is ineffective" finding does not transfer to it directly.
- Recommended split, drawn from the error-type findings: keep the deterministic gate for the cues whose omission or invention is high-cost and that checkers handle worst (causal links, hedge preservation, dates/end points/schedules); add a multilingual NLI checker (e.g. an XNLI-trained XLM-R/mDeBERTa, or MiniCheck on the Indonesian text if it holds up) as a residual pass over each arc sentence vs its cited articles to catch unsupported content the lexicon does not cover (wrong entities, out-of-article facts, which together make up 63% of FRANK errors).
- The project's recurring QA finding, that closed word lists fail on the first unlisted synonym, is the residual an NLI pass could cover. It should be measured on the project's own refused/passed arc sentences before it becomes a gate; at ~70-75% expected accuracy on Indonesian, it is more suitable as a "flag for retry/review" signal than as a hard refusal.

### Gaps
- No documented hybrid (rule + NLI) faithfulness gate for summarization was found in any language.
- No study compares cue-lexicon gates with NLI checkers on causal/hedge/temporal claims.
