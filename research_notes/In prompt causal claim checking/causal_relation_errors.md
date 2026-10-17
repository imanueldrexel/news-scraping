# Causal / relation / discourse-link faithfulness errors in abstractive summaries

Running example: a summary wrote "the court cannot disqualify the VP **because** the petition was inadmissible", while the sources gave two separate reasons: (a) the petition is inadmissible because the petitioners lacked standing; (b) disqualification is outside the court's authority. Both clauses are individually supported, but the causal link between them is invented. In FRANK's terms this is a **Discourse Link Error (LinkE)**. In TofuEval's terms it is closest to a **Reasoning Error** ("draws incorrect relations between A and B").

Method note: the primary PDFs (FRANK arXiv 2104.13346, Tang et al. arXiv 2205.12854, TofuEval arXiv 2402.13249, MiniCheck/LLM-AggreFact arXiv 2404.10774, FaithBench arXiv 2410.13210, FActScore arXiv 2305.14251, SummaC arXiv 2111.09525) were downloaded and read with pdftotext. Some multi-column tables extracted with shifted rows. Where the row-to-label mapping was ambiguous, this is flagged below.

## Q1. FRANK typology (Pagnoni et al., NAACL 2021): what LinkE and RelE are, how often they occur, and how well metrics detect them

### Takeaway
FRANK defines LinkE as an error "in how multiple statements are linked together in the discourse (for example temporal ordering/causal link)". It is rare in 2019–2020-era model summaries: about 0–9% of errors per model, and 0% on XSum because XSum summaries are a single sentence. Entity, out-of-article and coreference errors dominate. Pretrained models cut frame-level errors (PredE/EntE/CircE), but "discourse level errors still remain a challenge". In the metric ablation, the QA-based metrics (QAGS, FEQA) are *negatively* correlated with discourse errors, FactCC is "nearly uncorrelated", and only the dependency-level entailment metric DAE showed meaningful correlation.

### Cited Findings
- **Typology.** The categories are Predicate/Relation Error (PredE, called "Relation Error" in Table 1), Entity Error (EntE), Circumstance Error (CircE), Coreference Error (CorefE), Discourse Link Error (LinkE), Out-of-Article (OutE), Grammatical (GramE) and Other. They sit at three levels: semantic frame (PredE/EntE/CircE), discourse (CorefE/LinkE) and content verifiability (OutE/GramE). — [Pagnoni et al. 2021, FRANK, arXiv 2104.13346](https://arxiv.org/abs/2104.13346)
- **PredE definition:** "the predicate in a summary statement is inconsistent with the source text… the frame from a summary statement does not align with what is expressed in the source text." Example: "The Ebola vaccine was rejected by the FDA in 2019" (the source says approved). — [FRANK](https://arxiv.org/abs/2104.13346)
- **LinkE definition:** "errors involving a discourse link between different statements. These include errors of incorrect temporal ordering or incorrect discourse links (e.g. RST relations, discourse connectors) between statements." Table 1 example: "To produce the vaccine, scientists have to show successful human trials, then sequence the DNA of the virus" (wrong order). The discourse-error category is grounded in Rhetorical Structure Theory relations such as "Volitional Cause". — [FRANK](https://arxiv.org/abs/2104.13346)
- **Data and agreement.** Sentence-level annotation of 5 CNN/DM models and 4 XSum models, done on MTurk. Agreement with an expert annotator on 201 datapoints reached Cohen's κ = 0.86. — [FRANK](https://arxiv.org/abs/2104.13346)
- **Overall error rates.** 60% of annotated summaries contain at least one factual error: XSum 92%, CNN/DM 43%. On CNN/DM, BERTSum is 23% incorrect and BART 27%; on XSum the best model (BertS2S) is 83% incorrect. — [FRANK](https://arxiv.org/abs/2104.13346)
- **Dominant error classes.** "For the CNN/DM dataset, the most frequent classes of errors are Entity Error (EntE) and Coreference Error (CorefE). For the XSum dataset they are Out of Article Error (OutE) and Entity Error (EntE)." There are "no discourse errors (CorefE, LinkE) in the XSum dataset because the data only contains single sentence summaries." — [FRANK](https://arxiv.org/abs/2104.13346)
- **Per-model error shares (appendix table).** The labels below follow FRANK's main-text percentages; the extracted rows were shifted by one.
  - CNN/DM, LSTM S2S (74.8% incorrect): PredE 11%, EntE 46%, CircE 13%, CorefE 15%, LinkE 5%, OutE 14%, GramE 24%.
  - CNN/DM, BUS (62.6% incorrect): LinkE 9%, CorefE 17%, EntE 56%.
  - CNN/DM, PGN (26.5% incorrect): LinkE 0%.
  - CNN/DM, the two pretrained models (27.2% and 23.8% incorrect): LinkE 3% and 4%; CorefE 23% and 33%; PredE 10% and 4%; EntE 37% and 25%.
  - XSum models: LinkE 0–1%, CorefE 0–1%, PredE 10–16%, OutE 34–45%.
  - Mapping caveat: the main text says BERTSum 23% and BART 27%, but the extracted label order would put BERTSum at 27.2% and BART at 23.8%. Treat which pretrained model has which LinkE share (3% vs 4%) as uncertain. — [FRANK appendix table](https://arxiv.org/abs/2104.13346)
- **Pretraining helps frame errors, not discourse errors.** "the improved error-rate on the CNN/DM dataset can be attributed to improvements at the frame level (PredE, EntE, CircE) while the discourse level errors still remain a challenge. Errors CorefE, LinkE account for a higher proportion of errors in BERTSum and BART compared to the other models." — [FRANK](https://arxiv.org/abs/2104.13346)
- **Annotators confuse LinkE with relation errors.** In the agreement analysis, "there were relatively few discourse context errors LinkE, so the analysis is less statistically significant. Discourse context errors correspond to using a wrong connectors between different facts… These were confused with PredE and EntE (wrong relation)… there was no confusion in the other direction." CorefE was confused with "no error" 69.7% of the time, so crowd annotators often miss discourse errors. — [FRANK](https://arxiv.org/abs/2104.13346)
- **Metric ablation (Figure 5, variation in partial Pearson correlation when an error category is omitted):**
  - "Both QGA metrics have negative correlation with discourse errors suggesting that QGA metrics are not able to capture coreference errors or discourse link errors potentially due to the entity oriented questions in their training data."
  - "DAE has the highest correlation of all metrics with discourse errors suggesting that entailment at the dependency level can help model discourse errors (CorefE and LinkE). FactCC is nearly uncorrelated in this category."
  - ROUGE-L has "low correlation with discourse level errors". OpenIE (triple matching) is correlated with semantic-frame errors.
  - FactCC is "best at capturing semantic frame" errors.
  - Source: [FRANK](https://arxiv.org/abs/2104.13346)
- **Correlation drops on abstractive data.** Entailment metrics' partial correlation on XSum is "reduced by a factor of four" compared with CNN/DM. QAGS's overall partial correlation is low (ρ = 0.06) and FEQA's is not significant. — [FRANK](https://arxiv.org/abs/2104.13346)

### Inferences
- LinkE was rare in FRANK partly by construction: the CNN/DM summaries are near-extractive and the XSum summaries are a single sentence. Multi-sentence, multi-source LLM summaries like the court example have far more room for invented connectives, so FRANK's 0–9% figure is probably a lower bound for that setting.
- QA-based detectors (QAGS, FEQA, and by extension QAFactEval-style metrics) generate entity-centred questions. "Why can't the court disqualify the VP?" is rarely generated, so these metrics are structurally weak on causal links.
- The court example needs a detector that sees the whole summary sentence (both clauses plus "because") against evidence drawn from more than one source span. NLI at the right granularity can in principle do this; atomic-fact or QA pipelines tend to split the sentence and lose the link (see Q3).

### Gaps
- FRANK reports LinkE frequencies and metric-ablation figures only as bar charts. The exact per-metric correlation numbers for discourse errors were not extractable from the text.
- FRANK does not separate causal LinkE from temporal LinkE.

## Q2. Later work on LLM-era summaries: are errors more subtle or relational, and how accurate are detectors on them?

### Takeaway
After FRANK, benchmarks mostly **stopped measuring discourse/link errors separately**: AggreFact discarded them as "uncommon", and TofuEval did not annotate inter-sentential errors. The closest LLM-era category is TofuEval's "Reasoning Error". Detector accuracy on modern LLM summaries is modest:
- **FaithBench:** about 50–58% balanced accuracy on hard cases.
- **TofuEval:** open-source LLM judges at 50–60% balanced accuracy, and GPT-3.5 catches only about 50% of even easy extrinsic errors.
- **LLM-AggreFact leaderboard:** top systems at about 77% average balanced accuracy.

Detectors improved mostly on older models' "obvious" errors. No benchmark found reports detector accuracy on causal-link errors specifically.

### Cited Findings
- **Tang et al., "Understanding Factual Errors in Summarization" (ACL 2023)** merged nine annotated datasets into AggreFact. They found that "much of the recent improvement in the factuality detection space has been on summaries from older (pre-Transformer) models." — [Tang et al. 2023, arXiv 2205.12854](https://arxiv.org/abs/2205.12854)
- **Tang et al. dropped discourse errors.** Their unified taxonomy is {intrinsic, extrinsic} × {noun phrase, predicate}: "We discard discourse errors as these are uncommon and not present in most of our datasets." When mapping FRANK labels, PredE and GramE became extrinsic-predicate errors. — [Tang et al. 2023](https://arxiv.org/abs/2205.12854)
- **Error mix by model generation.** Models make about 50% extrinsic errors on CNN/DM, falling slightly from OLD to more recent models. On XSum the extrinsic share stays at about 70%. — [Tang et al. 2023](https://arxiv.org/abs/2205.12854)
- **Recall by error type (Table 5, AggreFact-CNN-Error).**
  - Sample sizes: intrinsic NP 183, intrinsic Pred 60, extrinsic NP 220, extrinsic Pred 129.
  - DAE recall: intrinsic NP 59.6, intrinsic Pred 53.3, extrinsic NP 67.7, extrinsic Pred 62.8.
  - QuestEval recall: 62.8 / 50.0 / 72.3 / 68.2 in the same order.
  - For these metrics, predicate errors are caught less often than noun-phrase errors. Other rows of the table (SummaC-ZS/Conv, QAFactEval, ChatGPT variants) did not extract cleanly, so they are not reported here.
  - "recent metrics like SummaC-Conv, QAFactEval and ChatGPT-based achieve higher recall for most error types… more recent factuality metrics are better at capturing obvious errors generated by less recent models."
  - "none of current factuality metrics can identify certain error types across datasets equally well."
  - Source: [Tang et al. 2023](https://arxiv.org/abs/2205.12854)
- **TofuEval (Tang et al., NAACL 2024): topic-focused dialogue summaries written by LLMs.**
  - The error taxonomy adds "Reasoning Error": "The summary sentence makes wrong inferences (e.g. it contains error in arithmetic calculation, it draws incorrect relations between A and B, or it makes wrong extrapolations) based on premises or pieces of evidence that are grounded in the source document."
  - Other new categories: Stating Opinion as Fact, Mis-Referencing, Tense/Modality, Nuanced Meaning Shift.
  - Error-type agreement reached Fleiss' κ = 0.78.
  - Source: [TofuEval, arXiv 2402.13249](https://arxiv.org/abs/2402.13249)
- **TofuEval detector results.**
  - "all evaluators perform fairly well at identifying… Extrinsic Information… That said, we do find that GPT-3.5-Turbo only detect 50% of such errors--approximately 30% lower than the rate for non-LLM based metrics. For the remaining error types, there is a large gap in the detection rate between LLM-based and non-LLM based metrics."
  - Open-source LLM judges score "between 50% and 60%" balanced accuracy, "barely better than the baseline".
  - "AlignScore even surpasses GPT-4" on main-topic MediaSum summaries.
  - Source: [TofuEval](https://arxiv.org/abs/2402.13249)
- **TofuEval left discourse errors out.** Limitations section: "we do not ask human evaluators to annotate factual consistency errors that may span beyond a single sentence… one type of inter-sentential error is a discourse error, as discussed in Pagnoni et al. (2021)." — [TofuEval](https://arxiv.org/abs/2402.13249)
- **FaithBench (Bao et al., 2024/2025)** annotates summaries from 10 modern LLMs in 8 families, chosen on the cases where detectors disagree. "even the best hallucination detection models have near 50% accuracies on FaithBench". The best F1-macro is 55% and the best balanced accuracy 58%, and GPT-4o-as-judge is among the detectors tested. Labels include "benign" hallucinations, those "supported by world knowledge, common sense, or logical reasoning". — [FaithBench, arXiv 2410.13210](https://arxiv.org/abs/2410.13210)
- **LLM-AggreFact (with MiniCheck, Tang, Laban & Durrett, EMNLP 2024)** unifies 11 grounding datasets: CNN, XSum, MediaSum, MeetingBank, WiCE, REVEAL, ClaimVerify, FactCheck, ExpertQA, LFQA, RAGTruth. The MiniCheck authors note "most datapoints in LLM-AggreFact require reasoning across multiple sentences" (they switched SummaC-ZS to paragraph chunks for this reason). Their synthetic training data is built to teach models "to check each fact in the claim and recognize synthesis of information across sentences". — [MiniCheck, arXiv 2404.10774](https://arxiv.org/abs/2404.10774)
- **LLM-AggreFact leaderboard (fetched 2026-10-17; no update date shown):**

  | Rank | System | Avg. balanced accuracy |
  |---|---|---|
  | 1 | Bespoke-MiniCheck-7B | 77.4% |
  | 2 | Claude-3.5 Sonnet | 77.2% |
  | 3 | Granite Guardian 3.3 | 76.5% |
  | 4 | Mistral-Large 2 | 76.5% |
  | 5 | gpt-4o-2024-05-13 | 75.9% |
  | 6 | FactCG-DeBERTa-L | 75.6% |
  | 7 | Qwen2.5-72B | 75.6% |
  | 8 | MiniCheck-Flan-T5-L | 75.0% |

  Source: [LLM-AggreFact leaderboard](https://llm-aggrefact.github.io/)
- **Multi-document LLM summaries hallucinate heavily.** On new multi-document benchmarks (news and conversation), "up to 75% of the content in LLM-generated summaries is hallucinated", with hallucinations more likely toward the end of the summary. Human evaluation of 700+ insights attributes most errors to instruction-following failures or overly generic insights. — [Belém et al., NAACL Findings 2025, arXiv 2410.13961](https://arxiv.org/abs/2410.13961)
- **Discourse structure in long-document summaries.** Factual inconsistencies "are more common in complex sentences and are associated with several discourse features". Using discourse-inspired chunking to aggregate NLI scores improves detection over several baselines. Exact numbers were not retrieved. — [Zhong & Litman, NAACL 2025, arXiv 2502.06185](https://arxiv.org/abs/2502.06185)
- **Granularity of NLI input.** SummaC showed that earlier NLI-based detection suffered from "a mismatch in input granularity between NLI datasets (sentence-level), and inconsistency detection (document level)". It fixes this by scoring each summary sentence against each source sentence and aggregating. — [Laban et al., SummaC, TACL 2022, arXiv 2111.09525](https://arxiv.org/abs/2111.09525)

### Inferences
- **Are relational errors harder to detect than entity or number errors?** The evidence leans yes, but it is indirect:
  1. FRANK: QA metrics are negatively correlated with discourse errors and FactCC is uncorrelated.
  2. Tang et al.: DAE and QuestEval recall on CNN/DM predicate errors is 5–13 points lower than on noun-phrase errors.
  3. TofuEval: every evaluator does best on extrinsic noun-phrase/event errors, and the gap widens on the other categories, including reasoning errors.

  No paper isolates causal-link errors with their own detector-recall number.
- **Benchmarks are blind to the court example.** The field's main benchmarks (AggreFact, TofuEval) explicitly excluded discourse/link errors. An error like "X because Y" built from two separately stated facts is therefore largely unmeasured in the LLM era, and leaderboard accuracy (about 77% on LLM-AggreFact) says little about it.
- **Sentence-level NLI may catch it, chunk-level may not.** Sentence-level NLI (SummaC, MiniCheck) checks the whole summary sentence, so it can in principle notice that the source never states the causal relation. But max-over-chunks aggregation can still pass it if one chunk happens to contain both clauses near each other. In the court example the reasons may come from different articles, which makes the "because" unsupported by any single chunk; this is a point in the detector's favour only if chunks are not concatenated.

### Gaps
- No primary source found with a frequency for causal-link or LinkE errors in LLM (GPT-4-class) news summaries specifically.
- TofuEval's per-type frequencies and recall (Figures 2 and 4) were not extractable as numbers from the PDF text. Only the qualitative statements above are quoted.
- Belém et al.'s up-to-75% is a share of hallucinated insight content and is not broken down by relation type.
- DiverSumm (multi-document news; Huang et al., NAACL 2024) was not retrieved within the tool budget.

## Q3. Causal hallucination specifically, and whether claim decomposition (atomic facts) preserves relations

### Takeaway
Little primary literature measures causal hallucination in summaries as a distinct error class. It appears as a sub-category in taxonomies ("causal fabrication", "unsupported inference", TofuEval's "Reasoning Error"). Atomic-fact methods (FActScore and its descendants) assume facts are independent. Splitting "X because Y" into "X" and "Y", both of which are supported, silently drops the relation unless the decomposer emits the relation as its own claim. The decomposition literature (Decomposition Dilemmas, NAACL 2025; DnDScore) documents that decomposition adds noise and strips context.

### Cited Findings
- **FActScore's founding assumptions (Min et al., EMNLP 2023):**
  1. "Whether or not an atomic fact is supported by C is undebatable."
  2. "Every atomic fact… has an equal weight of importance."
  3. "Pieces of information in C do not conflict or overlap with each other."

  It defines an atomic fact as "a short sentence conveying one piece of information". It notes that "even a single sentence is a mix of supported and unsupported facts, e.g., in 40% of the cases with ChatGPT". It states FActScore "is not applicable when the facts are more nuanced, open-ended, and debatable", and it measures precision only. — [FActScore, arXiv 2305.14251](https://arxiv.org/abs/2305.14251)
- **Decomposition Dilemmas (Hu, Long & Wang, NAACL 2025)** reports mixed effects of claim decomposition on fact-checking: "a trade-off between accuracy gains and the noise introduced through decomposition". It provides a categorisation of decomposition errors. The specific categories were not retrieved. — [Hu et al., arXiv 2411.02400](https://arxiv.org/abs/2411.02400)
- **DnDScore (EMNLP 2025)** describes decomposition (isolating atomic facts) and decontextualization (re-adding context) as having "conflicting purposes". A decontextualized subclaim is less atomic, so "it [is] unclear which part of the new claim requires verification." — [DnDScore, arXiv 2412.13175](https://arxiv.org/abs/2412.13175)
- **Causal categories in taxonomies.** A 2025 hallucination taxonomy lists relation-error hallucinations as "inconsistencies of a temporal, causal, or quantitative nature", and separates "Causal Fabrication" from "Unsupported Inference". This comes from a search snippet; the full paper was not read. — [Comprehensive taxonomy of hallucinations, arXiv 2508.01781](https://arxiv.org/abs/2508.01781)
- **Causality-aware news summarization.** A 2026 Expert Systems with Applications paper proposes a causality-aware summarization framework. Its premise is that abstractive systems "introduce errors by inferring unsupported causal relationships"; its pipeline extracts causal facts before the LLM summarises. Only the abstract/snippet was seen, and no error-rate numbers were retrieved. — [ScienceDirect S0957417426010560](https://www.sciencedirect.com/science/article/abs/pii/S0957417426010560)
- **TofuEval's Reasoning Error** ("draws incorrect relations between A and B") is the nearest benchmarked category to a fabricated causal link. Its worked example is arithmetic: 30k + 30k + 40k reported as 300k jobs. — [TofuEval](https://arxiv.org/abs/2402.13249)

### Inferences
- For the court example, a FActScore-style pipeline is likely to produce "The court cannot disqualify the VP" (supported) and "The petition was inadmissible" (supported). It would score 2/2 and miss the error. A detector catches it only if (a) the decomposer is told to emit relation claims ("the court cannot disqualify the VP *because* the petition was inadmissible"), or (b) verification runs on the undecomposed sentence.
- This is a design-level, not empirical, inference. No paper found measured the relation-loss rate of atomic decomposition on causal sentences.
- QA-based checkers have the same blind spot as decomposition: their questions target entities and spans, not "why".

### Gaps
- No primary study found that quantifies (a) how often LLM summaries invent causal connectives between separately stated facts, or (b) the recall of NLI, QA or LLM-judge detectors on that error class.
- The categories in the Decomposition Dilemmas error taxonomy were not retrieved, so it is unknown whether "lost relation" is one of them.

## Q4. Non-English, Indonesian or low-resource evidence

### Takeaway
Evidence is thin. Multilingual NLI-based faithfulness signals have been used for 45 XL-Sum languages, which include Indonesian (mFACE). IndoNLG's human evaluation includes a "consistency" dimension for Indonesian summaries. No Indonesian-specific benchmark of error *types* or detector accuracy, causal or otherwise, was found.

### Cited Findings
- **mFACE (Aharoni et al., Findings of ACL 2023)** uses a multilingual NLI model's entailment signal to filter training data and to control generation. It reports gains in automatic and human evaluation across 45 languages of XL-Sum. — [mFACE, arXiv 2212.10622](https://arxiv.org/abs/2212.10622)
- **IndoNLG (Cahyawijaya et al., EMNLP 2021)** human-evaluates Indonesian summarisation, including on Liputan6, with "Consistency (factual alignment between the summary and the source)" as one of four criteria. — [IndoNLG, arXiv 2104.08200](https://arxiv.org/abs/2104.08200)
- **Liputan6 (Koto, Lau & Baldwin, AACL 2020)** is a 215,827-pair Indonesian news summarisation dataset. Its error analysis of low-ROUGE summaries exposes issues with ROUGE and the models. No faithfulness error-type statistics were retrieved. — [Liputan6, ACL Anthology 2020.aacl-main.60](https://aclanthology.org/2020.aacl-main.60)

### Inferences
- An Indonesian pipeline would rely on cross-lingual transfer: a multilingual NLI checker (mFACE-style) or an LLM judge.
- In Indonesian, causal links are often expressed by connectives such as *karena*, *sehingga*, *akibat*, *oleh sebab itu*. Detectors trained on English synthetic perturbations (e.g. FactCC) are unlikely to have seen such connective swaps. This is not tested in any source found.

### Gaps
- No Indonesian, or other Southeast Asian, factual-consistency benchmark with fine-grained error types was found.
- No measured multilingual NLI accuracy on Indonesian summary faithfulness was found.
- SEAHORSE and similar multilingual faithfulness datasets were not checked for Indonesian coverage.
