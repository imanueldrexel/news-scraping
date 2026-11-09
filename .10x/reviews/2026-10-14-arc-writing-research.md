# Story arcs read like a chronicle: research and what to change (2026-10-14)

**Trigger (owner, after reading the SYS-150 replay):** "it's so obvious ... the end paragraph is just spitting out the arcs, there's no continuity in the story development". The example is 2026-10-11, "Polri Mutasi 199 Perwira, Kakorlantas dan Tiga Kapolda Berganti".

**Method:**
- desk research on news-writing craft (wire services, explanatory newsletters, Indonesian newsrooms);
- the SYS-150 replay's 19 arc editions as the corpus (`digests/preview/arcs/`);
- the arc prompt and checks read against both.

## 1. What is wrong (measured on the 5 replayed days)
- **69%** of the latar sentences (45 of 65) open with or carry "Pada d/m". **13 of 19** latar paragraphs hold three or more dates.
- The only latar that read like stories are the ones with no history (Panama earthquake, Batam blackout), because they had no list to recite.
- **Non-events are reported as events:** "Pada 5/10, peta mutasi 88 perwira itu dibahas"; "pada 7/10 disebut ...". A timeline item exists, so it is told.
- **No link to today:** the latar never says how the past changes the meaning of today's news (second wave? reversal? follow-through?). The reader must work out the arc.

**Root cause: the prompt asks for exactly this** (`newscrawler/core/story_arc.py`, `PROMPT`):
- "latar: ... ceritakan bagaimana peristiwa sampai ke hari ini, **urut waktu**, hanya dari cuplikan di alur, **setiap fakta bertanggal**";
- "**Setiap fakta dari LINI MASA ditulis dengan tanggalnya, mis. "Pada 24/9, ..."**";
- the worked example models it: "Pada 27/9, IHSG tercatat turun ... dan pada 30/9 analis memperkirakan ...";
- the date guard rewards it: an explicit `d/m` is the one time form code can verify, so the safest answer is a date per sentence.

## 2. How good news writers do it (craft principles)
1. **Frame, then evidence.** The background paragraph opens with what the past *means* for today, not with the oldest date:
   - a series ("gelombang kedua dalam dua pekan");
   - an escalation ("serangan ketiga dan yang paling mematikan");
   - a reversal ("setelah sempat naik sepekan");
   - a follow-through ("sepekan setelah Perpres-nya diteken").

   This is the *nut graf* idea from feature writing, and "the big picture" / "catch up quick" in briefing newsletters.
2. **Select, don't list.** One or two turning points that changed the situation, not every item. Drop process non-events (*dibahas, disebut, dikabarkan, ditanggapi*) unless they are the turn.
3. **Relate each past fact to today.** Use connectors that carry meaning: *kini, kali ini, berbeda dengan, setelah, menyusul, lanjutan dari, untuk pertama kali sejak*. Time-only connectors (*lalu, kemudian, selanjutnya*) just keep the chronicle moving.
4. **Relative time over calendar dates.** "awal Oktober", "sepekan lalu", "akhir September". Give a calendar date only when the date itself matters (a deadline, a vote, a scheduled hearing), and at most once or twice per paragraph.
5. **Vary the rhythm.** No two sentences open the same way. A paragraph whose sentences all start "Pada ..." reads as a log.
6. **End where it stands.** The last sentence says what is open now: who decides next, what is still disputed. Only when an article states it (decision 5 still holds), otherwise stop.
7. **Trust is unchanged:** every fact still comes from a chosen item, every cause is attributed. The craft changes the selection and the order, not the sourcing.

## 3. Before / after (only facts already in the arc's sources)

**Polri mutasi, 2026-10-11 (owner's example)**
- **Before:** "Mutasi ini melanjutkan perombakan yang berjalan sejak awal Oktober. Pada 3/10, Polri memutasi 88 perwira tinggi dan menengah termasuk 19 jabatan Kapolda lewat Surat Telegram Nomor ST/2205/X/KEP./2026. Pada 5/10, peta mutasi 88 perwira itu dibahas, dan pada 7/10 disebut Kapolda Metro Jaya kini dijabat Dadang Hartanto. Pada 9/10, Kapolri Suyudi Ario Seto memimpin sertijab, dan Komjen Dadang Hartanto resmi menjabat Kapolda Metro Jaya."
- **After:** "Ini gelombang kedua perombakan Polri bulan ini. Gelombang pertama di awal Oktober memindahkan 88 perwira dan mengganti 19 Kapolda, termasuk Kapolda Metro Jaya yang kini dijabat Komjen Dadang Hartanto. Kali ini giliran Korlantas dan tiga Polda lain."
- **Why:**
  - a frame sentence (series);
  - one turning point with its numbers;
  - the 5/10 and 7/10 non-events dropped;
  - a link back to today ("kali ini");
  - one date form, relative.

**IHSG, 2026-10-12**
- **Before:** "Pelemahan ini berlanjut sejak sebulan terakhir. Pada 24/9, IHSG anjlok 1,06% di sesi I ke 6.307, lalu pada 25/9 terkoreksi ke 6.241. Pada 26/9, IHSG ambruk 3,09% sepekan ke level 6.241,89 disertai net sell jumbo asing. Pada 1/10, IHSG melemah 1,02% ke 6.009,50 dan sempat menyentuh 5.973."
- **After:** "Level 6.000 sudah goyah sejak awal bulan: pada 1/10 IHSG ditutup di 6.009,50 setelah sempat menyentuh 5.973. Tekanannya bermula akhir September, ketika indeks turun 3,09% dalam sepekan disertai jual bersih jumbo investor asing."
- **Why:**
  - the frame is the threshold today's story is about;
  - two turning points instead of four closes;
  - "disertai" (stated), not an invented "karena".

## 4. What to change (for QA to ticket)
| # | Change | Where | Done when (suggested) |
|---|---|---|---|
| A | **Rewrite the latar instructions**: frame sentence first (what the past means for today: series / escalation / reversal / follow-through); at most 2 turning points; drop process non-events; link each past fact to today; relative time by default, at most 2 calendar dates; never two sentences opening the same way; end on what is still open only when stated. Replace "setiap fakta bertanggal" with "setiap fakta dari LINI MASA harus berasal dari cuplikannya". | `story_arc.PROMPT` | Replay: date-led latar sentences ≤ 25% (was 69%); ≤ 2 calendar dates per latar (13/19 had ≥ 3); owner prefers new over old arcs on ≥ 4/5 days |
| B | **Replace the worked example** with a narrative one (the IHSG "after" above, or a story from a day outside the replay set). The current example teaches the chronicle. | `story_arc.PROMPT` | The example latar opens with a frame and has ≤ 2 dates |
| C | **A chronicle check in code**, refuse-and-retry with reason `style`: a latar with > 2 calendar dates, or > 1 sentence opening "Pada <date>", or two sentences with the same opening word. The retry tells the model to synthesize. | `story_arc.parse`, `REASONS` | Unit tests per rule; the replay's arcs-accepted share stays ≥ 90% |
| D | **Verify relative time phrases.** Once A allows "awal Oktober", "akhir September", "sepekan lalu", "dua pekan terakhir", each must agree with a chosen item's date relative to the edition's date (e.g. "awal Oktober" ⇒ an item on 1-10 Oct). An unbacked phrase is refused as `date`. Without this, A trades a verifiable date for an unverifiable one. | `source_check` (new `relative_time_in` / check), `story_arc.parse` | Unit tests for each phrase family; an unbacked phrase is refused |
| E | **Ordinal and series claims** ("gelombang kedua", "ketiga kalinya", "untuk pertama kali sejak") are counts the model infers. Hold them to the chosen items: the ordinal ≤ chosen items + 1; "pertama kali sejak <date>" needs that item. Refuse as `number` otherwise. | `story_arc.parse` | Unit tests; replay hand-check shows 0 wrong ordinals |
| F | **Continuity check:** the latar's first sentence shares at least one event word with hari_ini or the judul, so the back-story is tied to today's news, not a free-standing recap. | `story_arc.parse` | Unit test; replay share of latar opening on a shared event word ≥ 90% |
| G | **Measure it:** the replay's metrics add date-led sentence share, dates per latar, non-event verbs used (*dibahas/disebut/dikabarkan*), and the first-sentence continuity share; `handcheck.csv` adds a `reads_as_story` y/n per arc for the owner. | `replay_story_arcs.py` | Metrics present; owner's re-read on 2 days |

**Order:** B with A (one prompt change), then D and E (guards that make A safe), then C and F (checks), with G alongside so A-F are measured. D and E are what keep the trust bar where it is: without them, prose that drops calendar dates can make claims code no longer checks.

**Re-validation plan:** re-run the replay on 2026-10-11 and 10-12 (≈ $0.25 at the peak price). The owner reads old arc vs new arc vs today's edition, blind, on the phone. Ship gate unchanged: arcs win ≥ 4/5 on the full 5-day set.
