# Adapting and evaluating NLI-based factual-consistency checkers for targeted error types (causal, hedge-drop, negation, end-date, unstated schedule) in Indonesian, on a small budget

Scope note: almost every quantitative result below is **English-only** unless marked [ID] (Indonesian) or [multilingual]. I found no published Indonesian evaluation of NLI/faithfulness checkers broken down by causal, hedging, end-date or schedule errors. IndoNLI is the only Indonesian source with per-phenomenon numbers.

## Q1. How well do NLI models handle causal, modality/hedging, negation, temporal and numeric inference?

### Takeaway
Off-the-shelf NLI models lose 25 to 35 points on negation and numeric stress tests in English. They fall to near zero on non-entailment cases where a shallow heuristic such as word overlap points the wrong way. In Indonesian, IndoNLI's expert set shows the same weak spots: numbers, comparatives, temporal and spatial reasoning. Negation does relatively better there. IndoNLI has no causal or modality/hedge category, so for 3 of the 5 target error types there is **no Indonesian measurement**, and the project would have to build its own targeted eval set.

### Cited Findings
**English stress tests (Naik et al. 2018 sets, re-run on transformers in 2020). English-only.**
- MNLI-fine-tuned large transformers on the Naik stress tests (matched partition). BERT-large: dev 86.0%, negation 57.3%, numerical reasoning 56.8%, antonymy 64.6%, word overlap 61.2%. XLNet-large: dev 89.2%, negation 60.0%, numerical 63.9%. RoBERTa-large: dev 90.0%, negation 59.0%, numerical 64.9%, antonymy 63.9%, word overlap 89.7% — [Aspillaga et al. 2020, "Stress Test Evaluation of Transformer-based Models in NLU Tasks"](https://ar5iv.labs.arxiv.org/html/2002.06261)
- Negation cost all three models 32 to 34 points; they confused entailment with neutral when a negation word was added. On numbers the models collapse onto one label instead of reasoning: XLNet predicts entailment about 90% of the time and RoBERTa neutral about 89% — [Aspillaga et al. 2020](https://ar5iv.labs.arxiv.org/html/2002.06261)
- The original Naik et al. stress-test suite covers negation, numerical reasoning (7,500 pairs built from algebra word problems), antonymy, word overlap, length mismatch and spelling. All models evaluated lost accuracy on every stress test — [Naik et al. 2018, COLING](https://arxiv.org/pdf/1806.00692)

**HANS (McCoy et al. 2019). English-only.**
- An MNLI-trained BERT scores 95/99/98% on HANS *entailment* items (lexical overlap / subsequence / constituent) but only 16/4/16% on *non-entailment* items. It labels nearly everything with high word overlap as entailed — [McCoy et al. 2019](https://ar5iv.labs.arxiv.org/html/1902.01007)
- Adding 30,000 HANS-like examples to MNLI's 392,702 (about 8%) brought all six HANS cells to about 100% — [McCoy et al. 2019](https://ar5iv.labs.arxiv.org/html/1902.01007). Inference: this is in-template generalisation, not proof of robustness on natural text.
- Relevance: an invented cause ("X naik **karena** Y") or a dropped hedge ("diduga" removed) has *very high lexical overlap* with the source. This is exactly the profile on which HANS shows NLI models say "entailed".

**Negation (Hossain et al. 2020 / 2022). English-only.**
- Negation is underrepresented in NLI benchmarks, and the few negations present can usually be ignored without changing the label. On a new benchmark where negation matters, state-of-the-art transformers struggle — [Hossain et al. 2020, EMNLP](https://aclanthology.org/2020.emnlp-main.732)
- In 8 NLU corpora, RoBERTa does substantially worse when a negation is present *and important* (its removal changes the label) — [Hossain, Chinnappa & Blanco 2022, ACL](https://ar5iv.labs.arxiv.org/html/2203.08929)
- Fine-tuning RoBERTa on pairs built from negated sentences and their affirmative interpretations beat three transformers with no negation fine-tuning, and also beat BERTNOT, on the new negation pairs, at comparable accuracy on the original dev splits — [Hossain et al., "Leveraging Affirmative Interpretations from Negation" 2022](https://arxiv.org/pdf/2210.14486) (summary via search snippet; exact deltas not retrieved)
- Further pre-training BERT/RoBERTa with self-supervised polarity tasks (Next Sentence Polarity Prediction) improved them on 9 negation benchmarks, by 1.8 to 9.1 points on CondaQA — [Rezaei & Blanco 2025](https://arxiv.org/abs/2502.07717)

**Modality / speaker commitment (closest analogue to dropped hedges). English-only.**
- CommitmentBank tests how far a speaker is committed to a clause embedded under an entailment-cancelling environment: conditional, negation, modal or question. A BERT-based NLI model reached 85% F1, but the authors conclude it "does not capture the full complexity of pragmatic reasoning" nor encode the relevant linguistic generalisations — [Jiang & de Marneffe 2019, EMNLP](https://aclanthology.org/D19-1630/)

**Temporal (TRACIE). English-only.**
- TRACIE has 5.5k crowd-sourced multi-premise entailment instances asking whether an implicit event *starts/ends before/after* an explicit one. State-of-the-art models struggle; a neuro-symbolic model (SymTime) gains 5 points, or 11 with zero prior knowledge — [Zhou et al. 2021, NAACL](https://arxiv.org/pdf/2010.12753). Its start/end comparator is the closest public analogue to the "wrong end date (hingga X)" error type.

**[ID] IndoNLI (Mahendra et al. 2021, EMNLP).**
- Size: 10,330 train / 1,657 dev / 2,401 test-lay / 3,008 test-expert (17,712 pairs). The expert set is tagged with 15 phenomena: MORPH, STRUCT, LSUB, NEG, COORD, QUANT, NUM, COMP, LEXSEM, IDIOM, COREF, SPAT, TEMP, CS (common sense), WORLD — [Mahendra et al. 2021](https://ar5iv.labs.arxiv.org/html/2110.14566)
- XLM-R accuracy per expert-set phenomenon: NEG 79.1, TEMP 69.6, NUM 65.0, COMP 59.5, SPAT 68.5, QUANT 75.1, CS 70.2, WORLD 69.0, LSUB 85.2, MORPH 84.4 — [Mahendra et al. 2021](https://ar5iv.labs.arxiv.org/html/2110.14566)
- Overall accuracy, test-lay / test-expert: IndoBERT-lite 74.1 / 58.9, IndoBERT-large 77.1 / 61.5, mBERT 72.5 / 57.3, XLM-R 82.3 / 70.3. Humans reach 85.1 / 89.1. A hypothesis-only baseline gets 59.8 on lay but only 46.0 on expert, so the expert set carries much less annotation artefact — [Mahendra et al. 2021](https://ar5iv.labs.arxiv.org/html/2110.14566)
- The abstract's "13.4% accuracy gap" is human 89.1 minus the best system 75.7 (translate-train). The gap for XLM-R trained on IndoNLI alone is 18.8 — [Mahendra et al. 2021](https://arxiv.org/abs/2110.14566)

### Inferences
- The five target errors line up with documented weaknesses as follows:
  - **Negation/denial flip**: NEG, Hossain, Naik negation.
  - **End date**: TEMP and NUM, TRACIE.
  - **Dropped hedge**: CommitmentBank-style modality.
  - **Invented cause**: HANS-style high overlap, no dedicated Indonesian set.
  - **Unstated future schedule**: an extrinsic hallucination that an NLI model should mark "neutral". Overlap-driven models may still say "entailed" when the event and date words both appear in the source.
- IndoNLI's NEG score (79.1) is good next to TEMP/NUM/COMP. However, IndoNLI negations are written by annotators, not dropped from news text. It does not show that XLM-R catches a *denial reported as fact* ("membantah" → stated).
- No public NLI set, English or Indonesian, targets "hedge removed" directly. CommitmentBank is the nearest, and it is about embedding verbs, not reportive hedges such as *diduga / disebut-sebut / kabarnya*.

### Gaps
- Not retrieved this session, so no numbers given: TaxiNLI per-category results, ConTRoL (contextual reasoning), MoNLI (monotonicity + negation), e-CARE / COPA-derived causal NLI. These are the main causal and logic sources; consult the papers directly.
- No Indonesian causal, modality or hedge NLI data found. No Indonesian TRACIE equivalent found.
- Exact negation deltas from Hossain 2020 / 2022 were not extracted (the PDF could not be parsed).

## Q2. Synthetic-error training for factual consistency: FactCC, Falsesum, DAE, CLIFF, SummEdits, LLM-generated data. Gains, error-type specificity, artefacts

### Takeaway
Synthetic perturbation training is the single biggest cheap gain: FactCC's weighted accuracy went from 51.5 (MNLI baseline) to 74.2, and Falsesum from 51.4 to 74.2 overall. Error types matter: removing one perturbation family costs measurable accuracy. The main risk is artefacts. Rule-based negatives can be told apart *without the premise* 82% of the time (FactCC), and simple synthetic errors do not match real abstractive errors (Goyal & Durrett). LLM-written, structured synthetic data (MiniCheck, TrueTeacher) is the current best cheap recipe.

### Cited Findings
- **FactCC** (Kryscinski et al. 2020) uses 6 rule-based transforms: back-translation paraphrase, entity swap, number swap, pronoun swap, **sentence negation**, noise. It trains BERT-base on 1,003,355 generated examples (50.2% negative). Weighted accuracy / F1 on human-labelled CNN/DM: BERT+MNLI 51.51% / 0.088, BERT+FEVER 52.07% / 0.086, FactCC 74.15% / 0.511 — [Kryscinski et al. 2020](https://ar5iv.labs.arxiv.org/html/1910.12840). English-only.
- **Falsesum** (Utama et al. 2022, NAACL) has a T5-base generator perturb human summaries into intrinsic or extrinsic errors; the checker is RoBERTa-base. Overall score MNLI-only 51.43 → MNLI+Falsesum (100k) 74.17. Per benchmark: FactCC 57.9→83.5, Ranksum 51.4→72.9, QAGS 52.7→75.1, SummEval 48.8→65.2 — [Utama et al. 2022](https://ar5iv.arxiv.org/html/2205.06009). English-only.
- Falsesum at equal size (100k): FactCC-style data gives 69.02 overall, DocNLI 55.35, Falsesum 74.17 — [Utama et al. 2022](https://ar5iv.arxiv.org/html/2205.06009)
- **Error-type ablation (Falsesum):** removing intrinsic examples costs −5.03, extrinsic −2.22, contrastive pairs −1.06. The most useful error family is the one that matches the target error distribution — [Utama et al. 2022](https://ar5iv.arxiv.org/html/2205.06009)
- **Artefacts:** with the premise removed, RoBERTa still classifies FactCC examples at 82.15% accuracy and Falsesum examples at 69.38%. Rule-based negatives carry strong hypothesis-only cues. Hand checks: 86% of Falsesum intrinsic and 81% of extrinsic examples really are inconsistent, so 14 to 19% label noise — [Utama et al. 2022](https://ar5iv.arxiv.org/html/2205.06009)
- **DAE / Goyal & Durrett 2021:** commonly used sets of simple synthetic errors "do not reflect errors made on abstractive datasets like XSum". Fine-grained human-labelled (arc/dependency-level) data is a better training signal than sentence-level labels or synthetic data — [Goyal & Durrett 2021, NAACL](https://aclanthology.org/2021.naacl-main.114)
- **CLIFF** (Cao & Wang 2021) applies contrastive learning *in the summariser*. Positives: synonym paraphrase, random word replacement, back-translation. Negatives: 4 strategies modelled on BART/PEGASUS error types. It produced more factual summaries than post-hoc correction, entailment reranking and unlikelihood training, by QA-based metrics and human judges — [Cao & Wang 2021, EMNLP](https://aclanthology.org/2021.emnlp-main.532). Note: a generator-side method, not a checker.
- **SummEdits** (Laban et al. 2023): 6,348 document-summary pairs in 10 domains, built from controlled *atomic edits* to verified summaries. Inter-annotator agreement is about 0.9 and it costs about 20x less per sample than earlier benchmarks. Balanced accuracy: GPT-4 82.06, still about 8 points below humans; Claude v2 73.58; Llama2-7b 50.36; most LLMs are near chance — [Laban et al. 2023](https://arxiv.org/abs/2305.14540v1); [EMNLP 2023](https://preview.aclanthology.org/setup/2023.emnlp-main.600). The atomic-edit protocol is the template for a cheap Indonesian targeted eval set.
- **MiniCheck** (Tang et al. 2024, EMNLP) has GPT-4 write structured synthetic errors in two schemes, C2D (7,076 instances) and D2C (7,319 instances), plus 21k ANLI examples, for about 35k training examples. MiniCheck-FT5 (Flan-T5-large, 770M) reaches 74.7% average balanced accuracy on LLM-AggreFact, against GPT-4 75.3, Claude-3 Opus 74.1, AlignScore 70.4 and SummaC-CV 62.1. On the test set it costs about $0.24 against GPT-4's $107 (about 400x cheaper). Backbones tried: RoBERTa-large, DeBERTa-large (both 355M) and Flan-T5-large — [Tang et al. 2024](https://arxiv.org/html/2404.10774v2). English-only.
- **TrueTeacher** (Gekhman et al. 2023, EMNLP) has an LLM label *model-generated* summaries rather than perturbed human ones: 1.4M released examples. The student beats similar-size models and the LLM teacher, and is robust to domain shift. A multilingual version (XLSum summariser over WikiLingua, LLM-labelled) improved results on 35 of 45 languages in mFACE (3,150 examples) — [Gekhman et al. 2023](https://arxiv.org/pdf/2305.11171); [ACL Anthology](https://aclanthology.org/2023.emnlp-main.127). [multilingual]; whether Indonesian was among the improved languages was not checked.
- Surveys covering this landscape: [Li et al. 2022, "Faithfulness in NLG: a systematic survey"](https://arxiv.org/pdf/2203.05227)

### Inferences
- **Do targeted perturbations help detect that error type?**
  - Indirect yes: HANS (+~84 points on in-template non-entailment), Falsesum's per-family ablation, and the negation fine-tuning work all show gains concentrated on the targeted family.
  - The caveat comes from Goyal & Durrett and Falsesum's 82% hypothesis-only score. Template-generated negatives (e.g. always deleting "diduga", always inserting "karena") teach the model to spot the *edit*, not to check the source.
  - Mitigations: (a) build negatives *and* matched positives with the same surface edit, e.g. a "karena" that the source really supports; (b) report a hypothesis-only baseline on the eval set; (c) evaluate on naturally occurring errors from the real generator (the newsletter's own outputs), not only on synthetic ones.
- For hedge-drop and invented-cause errors, the "contrastive pair" design is the right shape: same claim with and without the hedge or cause, labels determined by the source. Falsesum's −1.06 for removing contrastive pairs suggests the effect is real but modest in their setting.
- SummEdits-style atomic edits plus human verification give a cheap, high-agreement *evaluation* set. MiniCheck/TrueTeacher-style LLM generation gives cheap *training* data.

### Gaps
- No per-error-type recall numbers (e.g. "negation-flip recall before/after training") were retrieved for FactCC or Falsesum; they report aggregates.
- DAE's exact numbers (dependency-level F1 vs FactCC on XSum) were not retrieved.
- FactEdit was not retrieved.
- No Indonesian synthetic-error faithfulness dataset was found.

## Q3. Low-resource adaptation: translate-train vs zero-shot transfer, few-shot sizes, LLM-generated contrastive pairs, quality control

### Takeaway
For Indonesian NLI, zero-shot transfer of English-MNLI XLM-R (73.8) and translate-train (75.7) both *beat* XLM-R trained on native IndoNLI alone (70.3) on the hard expert set [ID]. A multilingual NLI backbone plus translated or LLM-generated targeted data is therefore a sound starting point. A few thousand to ~35k targeted examples have been enough in English (HANS 30k, MiniCheck ~35k). Quality control in the literature means hand checks (Falsesum 81 to 86% valid), hypothesis-only probes, and atomic-edit protocols with agreement checks (SummEdits ~0.9).

### Cited Findings
- [ID] XLM-R on the IndoNLI expert test: zero-shot from English MNLI 73.8; translate-train 75.7; translate-train (subset) 71.1. Trained on IndoNLI only: 70.3 — [Mahendra et al. 2021](https://ar5iv.labs.arxiv.org/html/2110.14566). Caveat: these numbers were extracted by a summarising fetch from the HTML tables. The 13.4-point human gap in the abstract (89.1 − 75.7) is consistent with translate-train being the best system.
- [ID] Monolingual IndoBERT-large (61.5 expert) trails multilingual XLM-R (70.3) by about 9 points on the expert set — [Mahendra et al. 2021](https://ar5iv.labs.arxiv.org/html/2110.14566)
- [multilingual] TrueTeacher's LLM-labelled multilingual synthetic data improved factual-consistency evaluation on 35 of 45 mFACE languages — [Gekhman et al. 2023](https://arxiv.org/pdf/2305.11171)
- LLM-generated errors need structure to be hard. MiniCheck's C2D/D2C procedures force multi-fact, multi-sentence reasoning; a decomposition step gave "near-zero" change for GPT-4 — [Tang et al. 2024](https://arxiv.org/html/2404.10774v2)
- Quality controls reported:
  - hand validation rate of generated negatives (Falsesum 81 to 86%) and a hypothesis-only probe (Falsesum 69% vs FactCC 82%) — [Utama et al. 2022](https://ar5iv.arxiv.org/html/2205.06009)
  - atomic edits checked by annotators, ~0.9 agreement — [Laban et al. 2023](https://arxiv.org/abs/2305.14540v1)
  - the hypothesis-only baseline as an artefact check on the eval set (IndoNLI expert 46.0 vs lay 59.8) — [Mahendra et al. 2021](https://ar5iv.labs.arxiv.org/html/2110.14566)

### Inferences
- Recommended LLM-contrastive-pair protocol, synthesised from the above:
  1. Take real source quotes from the project's articles.
  2. Have an LLM write *both* a faithful restatement and one targeted corruption per type: drop *diduga/disebut/kabarnya*; insert *karena/akibat/dipicu*; flip *membantah* to an assertion; change *hingga X*; add a date or schedule that is not in the source.
  3. Also generate **hard positives** that keep the same cue words where the source supports them.
  4. Hand-check a stratified sample (aim at or above Falsesum's 81 to 86% validity, or discard the family).
  5. Run a hypothesis-only classifier; above ~60% on balanced pairs means the edits leak.
  6. Hold out a natural-error set from real newsletter outputs.
- Translate-train of English stress sets (Naik negation, HANS, CommitmentBank) into Indonesian is cheap, but phenomena do not map one to one. Indonesian negation (*tidak/bukan/belum*) and reportive hedges have no direct English templates, so translated data should support, not replace, native LLM-written pairs.
- Starting checkpoint: a multilingual NLI model (XLM-R or mDeBERTa trained on MNLI/XNLI). IndoNLI shows multilingual beats monolingual IndoBERT on hard items.

### Gaps
- No study found that measures few-shot learning curves (e.g. 500/1k/5k targeted pairs) for Indonesian NLI.
- No published evaluation of LLM-generated Indonesian contrastive pairs (validity rate, artefact rate) was found.
- Whether Indonesian improved in TrueTeacher's mFACE results was not verified.

## Q4. Calibration and thresholding for a high-recall flag; combining a lexical rule gate with NLI

### Takeaway
Published checkers either use a fixed 0.5 threshold (MiniCheck) or tune one threshold per dataset on validation data (SummaC); neither studies calibration for a recall target. Granularity matters a lot: sentence-level NLI is about 17 points better than document-level (73.5 vs 56.4 balanced accuracy). A rule-gate-then-NLI design is not directly evaluated in the retrieved literature. The supporting evidence is indirect: NLI is weakest exactly where overlap is high, so a gate that names the risky construction tells the system where NLI must be strict.

### Cited Findings
- SummaC: NLI over the whole document against the whole summary scores 56.4% balanced accuracy; sentence-level pairs with aggregation score 73.5%; the learned aggregator SummaC-Conv scores 74.4%, about 5 points over prior work, against QuestEval 69.4. Thresholds were picked on validation data, one per dataset; sensitivity and calibration across domains are not discussed — [Laban et al. 2022, SummaC](https://ar5iv.labs.arxiv.org/html/2111.09525)
- SummaC: the best NLI backbone mixed MNLI and VitaminC training (ANLI was also tested); BERT-large beat base by about 1.3 points — [Laban et al. 2022](https://ar5iv.labs.arxiv.org/html/2111.09525)
- MiniCheck uses a fixed 0.5 threshold, not per-dataset tuning, and still reaches GPT-4 parity — [Tang et al. 2024](https://arxiv.org/html/2404.10774v2)
- NLI models fail asymmetrically. Near-perfect "entailment" on high-overlap items and near-zero on high-overlap non-entailment means the score is biased *toward accepting* the risky error types (HANS: 4 to 16% non-entailment accuracy) — [McCoy et al. 2019](https://ar5iv.labs.arxiv.org/html/1902.01007). On numbers, models collapse onto one label — [Aspillaga et al. 2020](https://ar5iv.labs.arxiv.org/html/2002.06261)

### Inferences
- **High-recall flag recipe:**
  1. Score at the sentence (claim) level against the cited quote, never the whole article (SummaC).
  2. Choose the threshold per error type on a held-out targeted set to hit a recall target, e.g. ≥0.9 recall on corrupted pairs, and report the false-flag rate on hard positives at that threshold.
  3. Re-check the threshold when the generator or model changes (thresholds do not transfer across datasets — SummaC tunes per dataset).
  4. Optionally temperature-scale the logits on that set. This step is standard practice; no faithfulness-specific source was retrieved.
- **Rule gate + NLI:**
  - The lexical gate ("the sentence asserts a cause / an end date / a schedule / a denial") picks the claim and the error type.
  - NLI then has to *entail* that specific proposition from the quote: "Y caused X", not just "X happened".
  - Gated claims get a stricter threshold (require P(entail) ≥ τ_type). Because HANS-type overlap bias inflates P(entail), a high τ (e.g. 0.8 to 0.9) is the natural high-recall setting.
- **Framing the NLI hypothesis:** frame it as the minimal proposition the gate found, e.g. "Kenaikan X disebabkan oleh Y" or "Acara Z dijadwalkan pada tanggal D". Do not use the whole newsletter sentence: overlap from the rest of the sentence is exactly what fools NLI.
- **Where the gate's own recall is weak:** the gate's recall on unlisted cue words bounds the system's recall. NLI cannot flag a claim the gate never routed.

### Gaps
- No retrieved paper evaluates calibration (ECE, reliability) of faithfulness checkers or recall-targeted thresholds.
- No retrieved paper evaluates a lexical-trigger + NLI hybrid against NLI alone.

## Q5. Concrete budget recipe: dataset sizes, model sizes, training time on a 6GB GPU or CPU

### Takeaway
Published scales are 30k to 100k synthetic examples on 125M to 770M models. HANS: +30k. MiniCheck: ~35k on 355M to 770M. Falsesum: 100k on RoBERTa-base. A 6GB GPU realistically fits a base-size (~125M to 280M) multilingual encoder at sequence length 256 with small batches and fp16. Training times on such hardware were not reported in the retrieved sources.

### Cited Findings
- Training scales that worked:
  - HANS augmentation 30k examples (~8% of MNLI) — [McCoy et al. 2019](https://ar5iv.labs.arxiv.org/html/1902.01007)
  - MiniCheck ~35k examples (14.4k synthetic + 21k ANLI) on 355M to 770M backbones — [Tang et al. 2024](https://arxiv.org/html/2404.10774v2)
  - Falsesum 100k examples on RoBERTa-base — [Utama et al. 2022](https://ar5iv.arxiv.org/html/2205.06009)
  - FactCC ~1M examples on BERT-base — [Kryscinski et al. 2020](https://ar5iv.labs.arxiv.org/html/1910.12840)
- Small checkers can match frontier LLMs: MiniCheck-FT5 (770M) 74.7 vs GPT-4 75.3 balanced accuracy, at 400x lower cost — [Tang et al. 2024](https://arxiv.org/html/2404.10774v2)
- [ID] Best Indonesian NLI starting point measured: XLM-R; translate-train 75.7 on the expert set — [Mahendra et al. 2021](https://ar5iv.labs.arxiv.org/html/2110.14566)

### Inferences (not sourced; engineering estimates)
- **Data:** for each of the 5 error types, aim for about 1k to 3k LLM-generated corrupted pairs plus an equal number of hard positives (≈10k to 30k total). Mix in an equal amount of general NLI (translated MNLI/XNLI or IndoNLI train, 10k) so the model does not forget general NLI.
  - Eval: about 200 human-verified pairs per error type in the SummEdits atomic-edit style, plus about 200 natural outputs from the live generator.
  - These sizes sit at the HANS/MiniCheck scale.
- **Model:** a multilingual base encoder already fine-tuned on XNLI/MNLI (~280M parameters with its large multilingual embedding). It fits 6GB VRAM at max_len 256, batch 8 to 16, fp16, with gradient accumulation. Large models (~560M) would need gradient checkpointing and batch ≤4. CPU fine-tuning of 20k pairs is plausible overnight for a base model but slow. These are standard-practice estimates, not measured.
- **Cost of data generation:** generating 20k to 30k short pairs with a cheap LLM API is on the order of a few dollars. This is not sourced; the project's own api_usage_log would give the real per-token cost.
- **Evaluation protocol:**
  - per error type: recall at the chosen threshold, false-flag rate on hard positives, and hypothesis-only accuracy (artefact check);
  - overall: performance on natural generator outputs.

### Gaps
- No retrieved source reports wall-clock training time for NLI fine-tuning on a 6GB GPU or CPU.
- No retrieved source gives a learning curve for targeted-error data size versus per-type recall.
