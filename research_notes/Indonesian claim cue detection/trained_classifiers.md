# Trained classifiers for hedge, negation, causal, temporal-end and future/plan cue detection (English, Indonesian, multilingual)

Scope note: research done 2026-10-21 with about 20 search/fetch calls. Numbers were taken from primary shared-task overview papers where I could parse them (the *SEM 2012 and CASE 2022 overview PDFs were downloaded and their tables read directly). Anything I could not confirm from a source is listed under Gaps, not stated as fact.

## 1. State-of-the-art P/R/F1 for hedge, negation, causal, and factuality/modality detection (English)

### Takeaway
Negation cue detection is close to solved in English: shared-task systems scored 90-92 F1 in 2012 and BERT models score about 93 F1. The reason is that the cue set is small and closed (30 unique cues in the Sherlock training set). Hedge/uncertainty detection is much harder outside biomedicine (60-70 F1 on Wikipedia "weasel" sentences). Sentence-level causal classification on news reaches about 86 F1 (recall 88-91, precision 81-84) with about 3k training sentences. Causal span and signal (trigger) detection reaches only about 49-60 F1. Factuality models look strong on the benchmarks but learn surface patterns.

### Cited Findings

**Negation (*SEM 2012 shared task, Conan Doyle "CD-SCO" corpus)**
- Corpus: 3,644 / 787 / 1,089 sentences (train/dev/test). It contains 984 / 173 / 264 negation cues, with 30 / 20 / 20 unique cues. Cues can be single words (*never*), multiword expressions, or affixes (*im-*, *-less*). — [Morante & Blanco 2012, *SEM 2012 overview](https://aclanthology.org/S12-1035.pdf)
- Best cue detection (closed track): FBK, P 93.41 / R 91.29 / **F1 92.34**, using CRFs with a special procedure for sub-token (affixal) cues. Other closed-track results: UiO1 r1 F1 92.10, UiO2 91.31, UMichigan 90.98 (R 87.88), UWashington 90.00. The best open-track cue score was 91.31 (UiO2). — [Morante & Blanco 2012](https://aclanthology.org/S12-1035.pdf)
- Scope resolution was much harder: best 72.40 F1 (UWashington) / 72.39 (UiO2). Negated-event detection reached 67.02 F1 (UiO1). The overview explains why cues score higher: "the set of negation cues is closed and comprises mostly single tokens, whereas scope sequences are longer." — [Morante & Blanco 2012](https://aclanthology.org/S12-1035.pdf)
- NegBERT (BERT, 2019/2020): cue detection F1 **92.94** on Sherlock. Token-level scope F1: 92.36 (Sherlock), 95.68 (BioScope Abstracts), 91.24 (BioScope Full Papers), 90.95 (SFU Review). The paper also analyses how well the model generalises to datasets it was not trained on. — [Khandelwal & Sawant, NegBERT, arXiv 1911.04211](https://arxiv.org/abs/1911.04211); [search summary of the same paper](https://cs.paperswithcode.com/paper/negbert-a-transfer-learning-approach-for)

**Hedge / uncertainty (CoNLL-2010 shared task, BioScope + Wikipedia weasel words)**
- CoNLL-2010 had two tasks. Task 1 detects uncertain (hedged) sentences at sentence level. Task 2 detects in-sentence cues and their scope. — [Hedge scope detection review, PMC4517914](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4517914/)
- Highest Task 1 Wikipedia result in the competition: Georgescul, **F1 60.2**, an SVM over bag-of-words. — [PMC4517914](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4517914/)
- A simple baseline got F=82.0 on the biological data and F=62.8 on Wikipedia, which shows how far the two domains are apart. — [Tjong Kim Sang 2010, CoNLL-2010 system paper](https://ifarm.nl/erikt/papers/conll2010.pdf)
- Later neural work on CoNLL-2010 Wikipedia: CNN+attention (Adel & Schütze 2017) F1 67.52. A GRU with POS features (2024) F1 **70.24**. Fine-tuned RoBERTa reached only **60.26** F1, and the authors say it overfitted. The training data is 11,110 sentences (about 10k after the dev split), and 77.26% of them are certain, so the classes are imbalanced. — [Hedge Detection in Text, arXiv 2405.13319 (2024)](https://arxiv.org/html/2405.13319v1)
- Scope on gold cues (biomedical): 71.92 F1 with a dependency-based boundary method. — [PMC4517914](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4517914/)

**Causal claims in news (Causal News Corpus, CASE 2022 shared task)**
- Data: 869 news documents and 3,559 English sentences. Subtask 1 (sentence: causal vs non-causal) is split train 2,925 (1,603 causal) / dev 323 / test 311 (176 causal). Subtask 2 (Cause/Effect/Signal spans) has only 160 train / 15 dev / 89 test sentences. — [Tan et al. 2022, CASE 2022 overview](https://aclanthology.org/2022.case-1.28.pdf)
- Annotator agreement is low. Subtask 1 Krippendorff's alpha is **34.99%** overall. Subtask 2 agreement is 6.96% exact match and 27.31% token overlap. Signal spans agree least: K-alpha 27.08%, token overlap 32.55%. — [Tan et al. 2022](https://aclanthology.org/2022.case-1.28.pdf)
- Subtask 1 leaderboard (R / P / F1):
  - CSECU-DSG 88.64 / 83.87 / **86.19**
  - ARGUABLY 91.48 / 81.31 / 86.10
  - LTRC 88.64 / 82.11 / 85.25
  - fine-tuned BERT baseline 84.66 / 78.01 / 81.20
  - LSTM baseline 84.66 / 72.68 / 78.22
  - "All the top-performing approaches involved pre-trained language models fine-tuned to the targeted task."
  — [Tan et al. 2022](https://aclanthology.org/2022.case-1.28.pdf); [overview record](https://core.ac.uk/works/135843945)
- Subtask 2 (spans) best overall macro F1 was **54.15** (1Cademy). Signal (trigger-word) F1 ranged from 48.92 (1Cademy) to **60.01** (IDIAPers, P 68.44 / R 56.12) and 56.32 (SPOCK). Only 64-76% of causal relations contain an explicit signal word, so the rest are implicit. — [Tan et al. 2022](https://aclanthology.org/2022.case-1.28.pdf)
- UniCausal (2022/2023) unifies six corpora: 58,720 sequence-classification examples, 12,144 span examples, 69,165 pair examples. Fine-tuned BERT baselines: **70.10** binary F1 for causal sequence classification, 52.42 macro F1 for cause-effect span detection, 84.68 binary F1 for causal pair classification. — [Tan, Zuo & Ng, UniCausal, arXiv 2208.09163](https://arxiv.org/pdf/2208.09163)

**Event factuality / modality (FactBank, UW, MEANTIME)**
- Factuality is usually treated as regression on a [-3, 3] scale and scored by MAE and Pearson r, not as P/R/F1. A multi-dataset graph-based model (Pouran Ben Veyseh et al. 2019) reported MAE 0.310 / r 0.903 on FactBank, 0.438 / 0.830 on UW, and 0.204 / 0.702 on MEANTIME. — [arXiv 1907.03227](https://arxiv.org/pdf/1907.03227)
- Rudinger et al. 2018 neural models gave large gains on FactBank, UW and MEANTIME. — [Neural models of factuality, NAACL 2018](https://aclanthology.org/N18-1067/)
- Jiang & de Marneffe 2021: "Although BERT obtains a strong performance on most datasets, it does so by exploiting common surface patterns that correlate with certain factuality labels, and it fails on instances where pragmatic reasoning is necessary." — [arXiv 2107.00807](https://arxiv.org/abs/2107.00807)

### Inferences
- The tasks rank in difficulty in the same order a gate lexicon would: negation cues (closed class) are easy, then the sentence-level causal claim, then hedges, then causal triggers/spans and pragmatic factuality, which are hard. Trained systems do best exactly where a curated word list also does best, a closed and mostly single-token cue set.
- The best signal-span F1 on news is about 49-60, and the human agreement on signals is about 27-33%. Both suggest that "which word is the causal trigger" is poorly defined even for people. A trained trigger tagger would not beat a curated lexicon by a wide margin there.
- The 60-70 F1 ceiling on Wikipedia weasel/hedge sentences means that general-domain hedging is not a solved problem, even with about 10k labelled sentences.

### Gaps
- I could not open the CoNLL-2010 overview (Farkas et al. 2010) for the biological Task 1 winner or the Task 2 cue-level F1. The ACL Anthology landing page showed no numbers. Only Georgescul 60.2 (Wikipedia) and the baseline figures are sourced here.
- I found no recent BERT-based speculation-cue F1 on BioScope or SFU from a primary source, though NegBERT's companion speculation work probably exists. I did not verify it.
- I found no P/R/F1 for FactBank-style "future/plan" (modality) detection framed as classification. The factuality literature reports MAE/r on continuous scales.
- I did not research CausalTimeBank, BECauSE, SemEval-2010 Task 8 Cause-Effect, or CASE 2023 (CNC v2) numbers.

## 2. Indonesian results (IndoBERT / IndoLEM / IndoNLU / NusaX) on causality, factuality, hedging, negation

### Takeaway
I found no Indonesian dataset or published model for hedge cues, negation cues, causal-claim detection, factuality, temporal end points or plan statements. The main Indonesian benchmarks (IndoLEM, IndoNLU, IndoNLI, NusaX) do not include these tasks. The closest resource is IndoNLI's expert-annotated test set, which probes temporal and numerical reasoning but provides no cue labels.

### Cited Findings
- IndoLEM covers seven tasks spanning morpho-syntax, semantics and discourse. Its IndoBERT is state of the art on most of them. None is a causal, hedge or negation task. — [Koto et al. 2020, IndoLEM and IndoBERT (COLING)](https://aclanthology.org/2020.coling-main.66); [arXiv 2011.00677](https://arxiv.org/abs/2011.00677)
- IndoNLU's IndoBERT was trained on Indo4B (about 4 billion words). — [IndoNLU, arXiv 2009.05387](https://ar5iv.labs.arxiv.org/html/2009.05387)
- IndoNLI (EMNLP 2021) has about 18K sentence pairs. Its expert-annotated test set targets numerical reasoning, structural changes, idioms, and temporal and spatial reasoning. The best model is still 13.4 accuracy points below humans on that set. — [Mahendra et al. 2021, arXiv 2110.14566](https://arxiv.org/pdf/2110.14566)
- A 2022 survey of negation and speculation corpora across languages says that annotated corpora outside English are growing but are "insufficient to address these important phenomena in languages with limited resources." — [Negation and Speculation in NLP: A Survey (Applied Sciences 2022)](https://www.open-access.bcu.ac.uk/13504/)
- Indonesian linguistics work describes causal compound sentences (*kalimat majemuk kausalitas*) and the causative verbs *membuat* and *menyebabkan*. This is descriptive or teaching material, not a computational dataset. — [repository.usd.ac.id 22791](https://repository.usd.ac.id/22791/); [kc.umn.ac.id BAB II](https://kc.umn.ac.id/id/eprint/47951/3/BAB_II.pdf)

### Inferences
- An Indonesian trained cue classifier would need a gold set built in-house: no off-the-shelf training data exists to fine-tune or probe on. The project's SYS-36 gold-set pipeline (LLM labels plus a hand check) is the realistic route.
- Cross-lingual transfer from English cue corpora is the only data-free alternative (section 4). No one has published that transfer for Indonesian.

### Gaps
- Searches in English and Indonesian ("deteksi kalimat kausal") found no Indonesian causal relation extraction paper with P/R/F1. A local journal (SINTA-indexed) paper may exist that a web search did not surface.
- I did not check NusaCrowd's catalogue entry by entry for a factuality, negation or causal dataset.
- I found no Indonesian temporal expression (TimeML/TIMEX) tagger results.

## 3. Sentence-level classifiers vs token-level cue taggers; label volume for about 90-95% recall; embedding + logistic regression vs fine-tuning

### Takeaway
A gate that must name the trigger word needs a token-level tagger, or a lexicon. A sentence-level head only says "this sentence states a cause or hedge" and cannot point at the word. On label volume:
- Fine-tuned sentence classifiers reached 88-91% recall at 81-84% precision on causal news with about 2.9k training sentences, but the labels themselves had alpha of only 0.35.
- Embedding heads (SetFit-style: a sentence encoder plus logistic regression) are competitive with full fine-tuning when labels are scarce (8 examples per class matched RoBERTa-large trained on 3k for sentiment).
- I found no study that reports the number of labels needed to reach 90-95% recall on cue detection specifically.

### Cited Findings
- CASE 2022 Subtask 1 is sentence-level. It reached 86 F1 and up to **91.48 recall** (ARGUABLY) with 2,925 training sentences. The fine-tuned BERT baseline got 84.66 recall / 78.01 precision. — [Tan et al. 2022](https://aclanthology.org/2022.case-1.28.pdf)
- In the same data, the token-level signal tagger reached at best 56.12 recall / 68.44 precision, trained on only 160 sentences. Span annotation is far more expensive and far less consistent: 6.96% exact-match agreement. — [Tan et al. 2022](https://aclanthology.org/2022.case-1.28.pdf)
- Token-level negation cue taggers reach 90-93 F1 with about 984 training cues (30 cue types). — [Morante & Blanco 2012](https://aclanthology.org/S12-1035.pdf); [NegBERT](https://arxiv.org/abs/1911.04211)
- SetFit trains a sentence-transformer body contrastively and then fits a classification head such as logistic regression. With 8 labelled examples per class on Customer Reviews sentiment, it is "competitive with fine-tuning RoBERTa Large on the full training set of 3k examples," and its results vary less from run to run. — [Hugging Face SetFit documentation](https://huggingface.co/docs/setfit/main/conceptual_guides/setfit); [SetFit docs index](https://huggingface.co/docs/setfit/index)
- On CoNLL-2010 Wikipedia hedges, fine-tuned RoBERTa (60.26 F1) did worse than smaller GRU models (70.24). The authors attribute this to overfitting on about 10k sentences. Bigger fine-tuned models are not automatically better on cue-style tasks. — [arXiv 2405.13319](https://arxiv.org/html/2405.13319v1)

### Inferences
- For "find the trigger word", sentence heads are the wrong shape. A logistic-regression head over a pooled e5-large or IndoBERT embedding scores the sentence. Any trigger attribution would be a post-hoc saliency step, which is unreliable. The realistic split is to let a lexicon (or a token tagger) name the word and to use a sentence head as a second, recall-oriented check that flags sentences the lexicon missed, for review or a rejection-with-reason.
- A sentence head is plausibly competitive for coarse labels (causal / hedge / denial / plan sentence) with a few hundred to a few thousand labels, based on the SetFit and CNC evidence. It will not reach 95% recall at high precision for causal sentences: the best fine-tuned systems sit at about 88-91% recall with about 81-84% precision, and the label noise (alpha 0.35) bounds what any model can show.
- The project already runs a frozen e5-large plus logistic-regression probe for topic/soft (SYS-37). The same architecture is the cheapest experiment to run, but it answers "does this sentence state X", not "which word".

### Gaps
- I found no learning-curve study for hedge, negation or causal cue detection that reports the number of labelled examples needed to reach 90% or 95% recall.
- I found no published evaluation of frozen multilingual-e5-large (or IndoBERT) embeddings with a linear head on cue or claim detection. I could not confirm the MTEB classification protocol (logistic regression on frozen embeddings) from the abstract alone, so I am not citing it.
- I did not verify SetFit results on multilingual or Indonesian data.

## 4. Cross-lingual transfer (English cue data to Indonesian or other low-resource languages)

### Takeaway
Zero-shot transfer works reasonably well for negation scope between European languages: up to 86.86 token F1 with mBERT/XLM-R, Spanish to Russian. No study tests English-to-Indonesian transfer for any of these cue types. Indonesian negation is mostly lexical (*tidak*, *bukan*, *belum*, *tanpa*), so it is likely easier than English affixal negation, but that is my inference, not a measured result.

### Cited Findings
- Shaitarova & Rinaldi (NAACL SRW 2021) ran zero-shot negation-scope transfer with multilingual BERT and XLM-RoBERTa between English, Spanish, French and Russian. The best result was 86.86% token-level F1 (Spanish to Russian). Performance correlated with negation typology and the models' lexical capacity. — [Negation typology and general representation models (2021)](https://preview.aclanthology.org/setup/2021.naacl-srw.3); [paper listing](https://physics.paperswithcode.com/paper/negation-typology-and-general-representation)
- Earlier neural cross-lingual negation-scope work (2018) exists. — [Neural networks for cross-lingual negation scope detection, arXiv 1810.02156](https://ar5iv.arxiv.org/html/1810.02156)
- Multilingual negation-scope work on legal text (2023) also tests transfer across languages. — [Resolving Legalese, arXiv 2309.08695](https://arxiv.org/pdf/2309.08695)

### Inferences
- English cue corpora are mostly literary (Sherlock), biomedical (BioScope) or review text (SFU), and the English causal news corpus is only 3.5k sentences. Transfer to Indonesian news would face a language shift and a domain shift together. A few hundred in-domain Indonesian labels would probably matter more than English training data.
- Typology matters, according to the 2021 study. Indonesian marks negation, aspect (*sudah*/*belum*/*akan*) and causality largely with free words rather than inflection, which favours lexicon and token approaches.

### Gaps
- I found no English-to-Indonesian (or any Austronesian-language) transfer results for negation, hedges, causality or factuality.
- I did not research multilingual causal corpora (e.g., multilingual CNC extensions) or multilingual factuality datasets.

## 5. Error profiles: implicit causality, rare cues, calibration, threshold choice for high recall

### Takeaway
Trained models miss the same things lexicons miss:
- implicit causal relations without a signal (32% of CNC relations overall; 24% in test, 36% in train, 44% in dev);
- sub-token or affixal and multiword negation cues;
- pragmatically conveyed factuality.

The top systems, though, show the high-recall operating point is reachable at sentence level: recall about 91% at precision about 81%.

### Cited Findings
- In CNC, the proportion of causal relations that have a signal word is 0.64 (train), 0.56 (dev), 0.76 (test), 0.68 overall, so about a third of causal relations are implicit. Signal spans average 1.47 words. — [Tan et al. 2022](https://aclanthology.org/2022.case-1.28.pdf)
- The CNC test sentences were longer than the training sentences (28.45 vs 17.21 words for Subtask 2) because short sentences were annotated first. This is a distribution shift that hurt span systems. — [Tan et al. 2022](https://aclanthology.org/2022.case-1.28.pdf)
- *SEM 2012: affixal (*un-*, *-less*) and multiword negation cues needed special handling. The best cue system (FBK) won by treating sub-token cues specially. — [Morante & Blanco 2012](https://aclanthology.org/S12-1035.pdf)
- BERT on factuality exploits surface patterns and fails where pragmatic reasoning is needed. The paper's title example, "He thinks he knows better than the doctors", is an embedded clause whose factuality depends on inference. — [Jiang & de Marneffe 2021](https://arxiv.org/abs/2107.00807)
- Hedge data is imbalanced (77% certain sentences in CoNLL-2010 Wikipedia), and RoBERTa overfitted on it. — [arXiv 2405.13319](https://arxiv.org/html/2405.13319v1)
- Different systems sit at different points on the precision/recall trade-off for the same task. On CNC Subtask 1, ARGUABLY had the highest recall (91.48, P 81.31) and CSECU-DSG the highest precision (83.87, R 88.64), with nearly equal F1. — [Tan et al. 2022](https://aclanthology.org/2022.case-1.28.pdf)

### Inferences
- For a fact-check gate whose failure mode is "an unsupported claim reaches the reader", the relevant miss is the implicit cause or the unlisted synonym. The CNC data says about 32% of causal relations have no trigger word at all. A trigger-word gate cannot see those. A sentence head can, but at a precision near 80%. This argues for a lexicon plus head design in which the head's positive and the lexicon's silence becomes a "refuse / ask" signal rather than an accept.
- Calibrate the threshold on the target (Indonesian news) distribution. The CNC length shift shows that dev-set thresholds do not carry over when the test distribution moves.

### Gaps
- I found no paper that reports calibration (ECE, reliability curves) for hedge, negation or causal cue classifiers, or a threshold for a fixed recall such as 95%.
- I found no measured rate of missed rare or unlisted cues for trained taggers versus lexicons on the same data.
