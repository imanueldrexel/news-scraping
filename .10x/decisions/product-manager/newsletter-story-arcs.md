# Newsletter story arcs (PM, 2026-10-13)

Status: **owner aligned 2026-10-13** (recommended scope, pure-prose layout) → principal architect. Successor to [newsletter-5min-edition](newsletter-5min-edition.md) (tracker #244). That scope stands except where this file replaces it.

## Problem
The owner says the edition is "too pointy, not storytelling", and that news is not aggregated across time ("instead of one day, see the n-past weeks, so we see the whole picture").

It is pointy by design. The 2026-10-05 scope asked for it:
- `story_summary.PROMPT` says "setiap kata harus membawa fakta" and "gaya kantor berita", with hard caps of judul 10, inti 25, poin 2×20 and mengapa_penting 20 words;
- the edition is 6 such stories plus about 29 one-line Sekilas items (`digests/2026-10-12-ringkas.md`).

It has no memory. Each story is written from at most 6 articles × 800 characters, all from the same day. The model cannot write "the third fall this week" or "two weeks after the first ratas", because it never sees that coverage. The knowledge base (88.6k entities, 482k mentions) and the NEWS_L1 vectors (months of coverage) are not read by the newsletter at all.

**Problem statement:** the reader gets the day's events as isolated facts, so the edition tells them *what* happened but not *how it got here or what comes next*. That is the understanding a briefing should add over scanning headlines.

## Target user
The owner, reading on the phone in Telegram at 12:00. Later a wider audience of readers who follow the economy and business (the 2026-10-05 owner decision), so the edition must stand alone.

## Owner decisions (2026-10-13, AskUserQuestion)
1. **Shape:** story arcs inside the daily edition. Rejected: a separate weekly synthesis, theme/entity tracks, prose-only with no history.
2. **Budget:** fewer, deeper stories. The edition stays at about 5 minutes / ≤ 1,200 words: 3-4 arc stories plus a short Sekilas.
3. **Lookback:** adaptive, up to 30 days. The arc goes as far back as the thread does, and a one-off story has no arc.
4. **Selection:** importance first, as today. A top story that has history gets an arc; a new story gets a "why it matters" paragraph instead.
5. **Look-ahead:** only when an article states it (a scheduled meeting, a deadline, a rule taking effect), with its source. Otherwise it is left out.
6. **Scope:** the recommended column below. P0 = thread finder + arc writer + guards + replay A/B as the ship gate; P1 story memory after the replay measures repetition.
7. **Layout: pure prose, no labels.** No Berlanjut/Baru kicker, no "Kronologi:" line, no "Agenda berikutnya:" label. Two or three flowing paragraphs. Continuity is said in the prose ("Persoalan ini sudah di meja Presiden sejak September"), and a stated look-ahead is the closing sentence. The PM's recommendation (kicker + Kronologi + Agenda) was declined.

## Research

### Corpus probe (EXPERIMENTS.md 2026-10-13, `scripts/experiments/probe_story_arcs.py`)
On 2026-10-12's 6 leads, 30-day lookback:
- **Vectors work, entities don't:** NEWS_L1 vectors found a real arc for 4/6 (karhutla from the 24/9 ratas; Houthi from the 6/10 Jeddah attack; IHSG and emas daily series), and correctly found none for the new lobster ban. The entity route returns 0 for concept stories (emas, lobster, daya beli) and drifts through generic places (IHSG → Houthi via "Timur Tengah").
- **No cosine floor separates thread from topic:** 0.70 includes loose matches; 0.80 cuts Houthi from 9 days to 2. So retrieval must be wide, and the LLM must confirm membership, item by item, which the guards then check.
- **Running series** (IHSG, emas) return hundreds of near-identical daily items. An arc needs 2-4 turning points, not 30 days of closes.
- **KB entity duplicates** across languages (Arab Saudi / Saudi Arabia). Entities only become useful after the entity-links merge (#315, parked).

### Precedent formats (desk research)
| Format | What it does | What we take |
|---|---|---|
| Axios Smart Brevity | Short story + labelled context: "Why it matters", "The big picture", "What's next", "Catch up quick" | Context in one labelled line is skimmable; "What's next" is their most-reused label |
| Semafor Signal | Separates "The News" (fact) from "Know More" (context) and "The View From" (attributed views) | Separate fact from view. This is our trust rule: causes and views only with a source |
| NYT The Morning | One lead told as a narrative, then quick bullets | Precedent for "few deep + many short", which is exactly decision 2 |
| Google News Full Coverage, Particle | Machine-built "story so far" timelines across days | Automated timelines are expected; their known failure is linking unrelated stories, which is our drift risk |
| Indonesian outlets (Kompas, Tempo, Katadata) | "Kronologi", "Kilas balik", "Duduk perkara" boxes | Indonesian readers already know "Kronologi" as a label |

What readers of narrative briefings value, distilled:
1. **What is new first.** A returning reader must not re-read yesterday's back-story to find today's change.
2. **Context in a sentence or two,** not an essay.
3. **Fact clearly apart from interpretation.**
4. **A visible stopping point.** They know when they are done.

The biggest risk storytelling adds is **invented causality**: "IHSG fell *because* the rupiah weakened" reads naturally but is often not stated in any article.

### Research plan (one reader now, wider audience later)
- **Phase 1, done:** desk research + corpus probe (above).
- **Phase 2, concept test:** replay 2026-10-12 with the arc prompt. The owner reads it on the phone, then answers 3 questions: what did you learn that the current edition did not tell you; where did you stop; did anything feel invented.
- **Phase 3, blind A/B:** 5 replayed days (incl. consecutive days 10-08..10-12, to see repetition). Current vs arc edition, order randomised. The owner picks the one they would rather read, with a one-line reason.
- **Phase 4, diary:** for the first 7 delivered editions, the owner replies to the Telegram message with a score of 1-5 and "anything new to you? y/n".
- **Later, wider audience:** 5-8 interviews with target readers (investors, finance professionals). Guide:
  - warm-up;
  - how they follow the news today (sources, times, what they skip);
  - deep dive (the last story they followed over weeks: how did they catch up?);
  - reaction (two editions side by side);
  - wrap-up.

## Approaches
| | MVP: arc writer | **Recommended: arc writer + guards + A/B gate, then story memory** | Full vision |
|---|---|---|---|
| What | For the 3-4 top stories: L1 neighbours over 30 days, one per day, an arc prompt, the new layout | MVP + an item-by-item drift guard + number/date/agenda guards + a replay harness and the owner's A/B as the ship gate. **P1:** persist each day's featured stories (summary + vector) so an arc says what changed since the last edition and does not repeat its back-story | + entity-centric threads (after #315 merge/links), "Efek berantai", a Tanya Berita thread page, a weekly synthesis |
| Cost | +3-4 LLM calls/day (~10k tokens, < $0.01) | same; story memory adds a table, no calls | entity-links pass ~$20 one-off + new surfaces |
| Risk | drift and invented causes shipped unchecked; IHSG back-story repeats daily | measured before shipping | blocked on owner's price DB (#315) |
| Size | ~2-3 dev sessions | ~4-5 sessions (P0 3, P1 1-2) | multi-week |

**Recommendation: the middle column.** The probe shows the data supports arcs, and the cost is negligible, but storytelling raises the trust risk. A guard set and a blind A/B on replayed days are the cheapest way to know before the owner reads it daily. Story memory is P1. Build it once the replay of consecutive days measures how much the back-story repeats (it will, for IHSG and emas).

## Prioritised requirements
- **P0**
  - **Thread finder:** for each of the edition's top 3-4 stories, NEWS_L1 neighbours of the story's articles within 30 days before the date, wide floor (≈0.70, tuned in replay), at most one item per day (the most-reported), at most ~10 items, given to the model as dated snippets (DB headline + opening ~300 chars).
  - **Arc writer:** the prompt below; the model returns which timeline items belong to the thread (`alur`). A story with no `alur` is "Baru" and gets a "why it matters" paragraph.
  - **Guards** (extend SYS-80/82/87):
    - numbers ⊆ today's articles ∪ the chosen `alur` items;
    - every date written in `latar` ("24/9", "24 September") matches the date of a chosen `alur` item, or today's (no free dates);
    - every `alur` item passes a subject check against today's story (a shared name or 2 content words, `story_words`);
    - `agenda` empty unless its date/event appears in a source;
    - refuse, retry once, then fall back to today's current summary.
  - **Layout + copy:** below; the edition's word budget re-split (60-detik ~80, 3-4 arcs × ~170, Sekilas ~280).
  - **Replay harness + owner A/B** (Phases 2-3) as the ship gate.
- **P1**
  - **Story memory:** each delivered story persisted with its vector; an arc on a story featured in the last 7 days writes "since <date>" and does not repeat back-story sentences.
  - **Causal-claim check:** a sentence with *karena / akibat / dipicu / memicu / sehingga / imbas* must carry an attribution (*menurut, kata, ujar*) or be copied from an article.
- **P2:** entity signals (after #315: merged entities as a second drift check, "Terkait" names).
- **P3 / won't do now:** weekly synthesis, per-reader threads, web thread page, images/charts.

## User stories
- As a reader, I want each top story to tell me how it got here, so I understand today's event without having followed it for weeks.
- As a returning reader, I want what's new today first, so I don't re-read yesterday's back-story.
- As a reader, I want to know which stories are continuing and which are new, so I know where to pay attention.
- As a reader, I want "what's next" only when it is actually scheduled, so I can trust the look-ahead.
- As a reader, I want to trust every number and every "because", so causes are attributed and numbers come from the articles.

## Success criteria
1. **Preference (leading):** the owner prefers the arc edition on ≥ 4 of 5 blind replayed days.
2. **Arc precision:** ≥ 90% of the `alur` items used in `latar` judged "same thread" by hand (owner or QA) over 5 days (~40-60 items).
3. **Trust:**
   - 0 numbers or dates outside the sources (guard);
   - ≤ 1 factual error across the arc stories of 3 hand-checked editions;
   - 0 unattributed causal claims in the hand-check;
   - 100% of `agenda` lines traceable to an article sentence.
4. **Length:** edition ≤ 1,200 words every day; the owner finishes it on the phone in ≤ 5 minutes (3 editions).
5. **Coverage holds:** ≥ 5 of the day's 6 largest stories in an arc story or Sekilas (the existing criterion).
6. **Cost:** newsletter ≤ $0.05/day (existing CTO criterion).
7. **Diary (lagging):** average ≥ 4/5 over the first 7 editions, "learned something new" on ≥ 5/7.
8. **P1, repetition:** for a story featured on consecutive days, ≤ 30% of `latar` sentences repeat the previous day's.

## Copy (Bahasa Indonesia; all strings go to `core/newsletter_copy.py`)

### Arc story layout (owner decision 7: pure prose, no labels)
```
### Asap karhutla sampai negara tetangga, Prabowo rapat lagi

Presiden Prabowo Subianto memimpin rapat terbatas karhutla di Istana Negara, Senin (12/10),
bersama Panglima TNI dan Kepala BNPB. Menko Polkam Dudung Abdurachman menyebut asapnya
sudah sampai ke negara tetangga.

Persoalan ini sudah di meja Presiden sejak September. Pada 23/9 Sekretariat Kabinet
melaporkan 209 hektare lahan masih terbakar, dan sehari kemudian Prabowo menggelar rapat
pertama dengan memanggil para ahli. Titik panas sempat turun pada awal Oktober, lalu naik
lagi di Kalimantan Tengah dan Sumatra Selatan pekan lalu.

<agenda, only when an article states it, as a closing sentence with its source, e.g.
"Rapat lanjutan dijadwalkan Kamis (15/10), menurut Seskab.">

Diberitakan 14 portal · Baca di CNBC Indonesia →
```
(Illustrative. Written from the probe's headlines, not a model output.)

### New-story variant
```
### Ekspor benih lobster distop permanen, Satgas dibentuk

<hari_ini paragraph>

<why-it-matters paragraph: only impact stated by the articles or their sources>

Diberitakan 16 portal · Baca di CNBC Indonesia →
```

### Labels
None inside a story (owner decision 7). The PM's recommendation, declined, is kept here for the record: kicker *Berlanjut sejak <date>* / *Baru*, a **Kronologi:** line, and **Agenda berikutnya:**. The prose has to carry continuity on its own. That is a prompt requirement ("katakan sejak kapan persoalan ini berjalan"), and the A/B checks it.

| Element | Copy |
|---|---|
| Footer disclosure | *Ringkasan dan alur cerita ditulis AI dari artikel 30 hari terakhir dan bisa keliru; cek artikel aslinya.* (discloses the new 30-day reach) |

Kept as they are: "Hari Ini dalam 60 Detik", "Sekilas", "Diberitakan N portal", "Baca di <outlet> →". "Berita Utama" stays as the section name. "Mengapa penting:" disappears from arc stories: it becomes the new story's second paragraph.

### Localization / tone notes
- Dates in prose are "24/9" (the existing house rule); the date guard parses this form and "24 September".
- Time connectives ("sebelumnya", "sejak", "sepekan kemudian") are free. Causal ones are not (see the prompt).
- Prose gets more room than the old caps: hari_ini ≤ 60 words, latar ≤ 70 words, agenda ≤ 20 words, at most ~170 words per story.

## LLM prompt (draft for the architect/SDE; replaces `story_summary.PROMPT` for the edition's top stories only)
The full digest's per-cluster summaries are unchanged. The arc writer is a second call, for 3-4 stories.

```
Kamu redaktur briefing berita harian berbahasa Indonesia. Tugasmu menceritakan SATU berita utama
hari ini sebagai alur: apa yang terjadi hari ini, bagaimana sampai ke sini, dan agenda berikutnya
bila ada. Pembacamu cerdas tetapi sibuk dan membaca di ponsel.

Di bawah ada dua bagian:
- HARI INI: {n} artikel {tanggal} yang dikelompokkan mesin sebagai satu berita. Pengelompokan ini
  bisa salah.
- LINI MASA: {m} cuplikan berita bertanggal dari 30 hari sebelumnya, dicari mesin karena MIRIP.
  Mirip belum tentu satu alur.

LANGKAH
1. Tentukan SATU peristiwa hari ini yang dibahas paling banyak artikel HARI INI. Nomor artikel yang
   membahas peristiwa lain masukkan ke "tidak_terkait".
2. Dari LINI MASA, pilih HANYA cuplikan yang merupakan tahap sebelumnya dari peristiwa yang sama:
   yang memicu, mendahului, atau menjadi langkah sebelumnya. Berita lain yang hanya bertopik mirip
   (harga lain, tokoh yang sama di urusan lain, wilayah yang sama) BUKAN alur. Untuk berita harian
   yang berulang (penutupan IHSG, harga emas), pilih hanya titik balik, bukan setiap hari.
   Jika tidak ada yang cocok, "alur" kosong.
3. Tulis hanya dari teks di bawah. Jangan menambah fakta, angka, nama, jabatan, tanggal, sebab,
   atau dampak yang tidak tertulis.

ATURAN TULISAN
- Tulis sebagai cerita pendek yang mengalir: paragraf dengan kalimat yang bersambung, tanpa
  daftar, tanpa label, tanpa poin. Bahasa
  Indonesia baku, kalimat aktif, tanpa clickbait, tanpa tanda seru, tanpa pertanyaan retoris.
- Mulai dari yang BARU hari ini. Latar datang sesudahnya.
- Kata sebab-akibat ("karena", "akibat", "dipicu", "memicu", "sehingga", "imbas") HANYA boleh
  dipakai jika hubungan itu tertulis di teks, dan sebutkan siapa yang mengatakannya: "yang menurut
  analis Phintraco Sekuritas dipicu ...". Kata urutan waktu ("sebelumnya", "sejak", "sepekan
  kemudian") boleh dipakai tanpa sumber.
- Setiap fakta dari LINI MASA ditulis dengan tanggalnya, mis. "Pada 24/9, ...".
- Proyeksi, klaim, dan pendapat selalu diberi sumber. Jangan menyajikan proyeksi sebagai fakta.
- Salin angka persis seperti di teks. Jangan membulatkan, menjumlahkan, atau menghitung selisih
  sendiri: tulis angka yang tertulis saja.
- Rp tanpa spasi (Rp2.574.000), tanggal hari ini sebagai "Senin (12/10)", kode saham sekali dalam
  kurung: Telkom (TLKM).
- Jangan menulis fakta yang sama dua kali.

Balas HANYA dengan JSON valid, tanpa teks lain:
{{"judul": "...", "hari_ini": "...", "latar": "...", "agenda": "...", "sekilas": "...",
  "terkait": [0, 1], "tidak_terkait": [2], "alur": [3, 5, 8]}}

- judul: maks 10 kata. Apa yang berubah hari ini. Bukan salinan judul portal.
- hari_ini: 2-3 kalimat, maks 60 kata: apa yang terjadi hari ini, siapa, angka terpenting, dan
  bila ada satu kaitan terpenting dengan alur.
- latar: 2-3 kalimat, maks 70 kata.
  - Jika "alur" berisi cuplikan: ceritakan bagaimana peristiwa sampai ke hari ini, urut waktu,
    hanya dari cuplikan di "alur", setiap fakta bertanggal.
  - Jika "alur" kosong: tulis mengapa peristiwa ini penting, HANYA dampak yang disebut artikel atau
    narasumbernya; "" jika tidak ada.
  - Jika alur berjalan lebih dari beberapa hari, katakan sejak kapan persoalan ini berjalan.
- agenda: maks 20 kata. HANYA langkah berikutnya yang terjadwal atau sudah diumumkan dan tertulis
  di teks (tanggal rapat, tenggat, berlakunya aturan), dengan sumbernya. "" jika tidak ada.
  Jangan menebak.
- sekilas: 1 kalimat, maks 15 kata.
- alur: nomor cuplikan LINI MASA yang kamu pakai. Semua fakta di "latar" harus berasal dari
  cuplikan ini.
Batas kata di atas mutlak: jawaban yang melebihinya ditolak.

CONTOH JAWABAN
<one worked example from a past day that is never the day being written: SDE picks it in replay>

HARI INI
[0] <outlet> — <headline>\n<opening, 800 chars>
...
LINI MASA
[{n}] <Hari>, <d> <Mon> · <outlet> — <headline>\n<opening, 300 chars>
...
```
Indexes run on: today's articles are 0..n-1, the timeline n..n+m-1, so `terkait` and `alur` never collide.

## What we are NOT building
- A weekly edition.
- Theme or entity pages.
- Per-reader threads.
- Web or email delivery.
- Charts.
- Changes to clustering or to the full archive digest.
- Entity-links work (#315 stays parked).
- A timeline/Kronologi line or any in-story label (owner decision 7).

## Risks and early signals
| Risk | Early signal | Mitigation |
|---|---|---|
| Drift: unrelated past news woven into the arc | arc precision < 90% in Phase 3 hand-check | item-by-item `alur` confirmation + subject guard; tune the floor in replay |
| Invented causality | unattributed "karena" in hand-check | prompt rule; P1 causal-claim check |
| Repetition on consecutive days (IHSG, emas) | latar repeat share > 30% on 10-08..10-12 replay | P1 story memory |
| Pure prose hides that a story is continuing | owner misses the continuity in Phase 2 | prompt rule "sejak kapan"; revisit labels only on owner request |
| Word budget blown by prose | edition > 1,200 words | 3 arcs when long; Sekilas trims first (existing rule) |
| Fewer top stories hide a big event | coverage < 5/6 | the 6 largest are still guaranteed a Sekilas line (existing rule) |
| Owner doesn't prefer it | A/B < 4/5 | stop before scheduling; keep the current edition |
