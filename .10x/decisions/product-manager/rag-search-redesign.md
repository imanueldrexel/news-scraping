# RAG search redesign (PM, 2026-10-07)

**Owner decision (2026-10-07):** the RAG search web UI is the **next top priority**. Tracker #272, label `priority: next`.

**Source:** the 2026-10-07 design critique and UX-copy review of `newscrawler/web/` (in-session; findings verified against production, read-only).

## Problem
The page works, but it reads as a developer test page and hides what makes RAG trustworthy:
- the sources are collapsed, and the citations can't be clicked;
- 4 of 5 category filters match 0 articles;
- model failures show raw exceptions;
- the reader sees internal names, raw dates, "chunks" and timings;
- the answer calls Gemini directly, capped at 20/day;
- the answer is rendered unescaped.

## Tickets, in build order
| Order | Ticket | Kind | What |
|---|---|---|---|
| A1 | SYS-93 #262 | bug P2 | Escape the model's answer (security) |
| A2 | SYS-92 #261 | bug P2 | Topic filter on `articles.topic` |
| A3 | SYS-94 #263 | bug P2 | Answer states instead of raw exceptions |
| A4 | SYS-95 #264 | bug P3 | Outlet names, Indonesian dates; no chunks / timings |
| A5 | SYS-96 #265 | bug P3 | Contrast, labels, named buttons |
| A6 | SYS-97 #266 | bug P3 | Conversation thread + "Pertanyaan baru" |
| B1 | SYS-98 #267 | enhancement | Answers through the shared `Summarizer`; provider by config; ADR |
| B2 | SYS-99 #268 | enhancement | Answer prompt, numbered linked citations, number check |
| C1 | SYS-101 #270 | enhancement | Copy table, reader copy, empty states |
| C2 | SYS-100 #269 | enhancement | Filters: outlet dropdown, date chips, topic chips |
| C3 | SYS-102 #271 | enhancement | Visual redesign, mockup first |

## Open owner decisions
- **SYS-98:** answers on DeepSeek via the shared Summarizer (PM recommendation: one key, spend tracking, no 20/day cap) or stay on Gemini.
- **SYS-102:** approve the mockup before the visual build.

## Success criteria
- Every filter option returns results in its scope.
- No raw exception, English developer text, internal source name, raw date or "chunk" anywhere in the page.
- Every answer cites `[n]` links that resolve to a visible source card; a number not in the cited articles is flagged.
- The answer is available every day, and degrades to "articles only" with a clear message.
- WCAG 2.2 AA contrast and labels in light and dark.

## Glossary (reader-facing)
artikel = one document · portal = an outlet · topik = a section · sumber = the list behind an answer. Never chunk, query, RAG, kategori or konteks in reader text.

**Register:** neutral journalistic Indonesian. Address the reader rarely; when needed, *Anda*.

## Copy (SYS-101, SYS-94, SYS-97, SYS-100)
**Title, hero, search**
- Tab title: `Tanya Berita · NewsAggregator`; H1 `Tanya Berita`.
- Hero line: `Jawaban disusun dari {n} artikel di {portals} portal berita, lengkap dengan sumbernya. Diperbarui {jam} WIB.`
- Placeholder: `Contoh: Kenapa rupiah melemah pekan ini?`; button: `Tanya`.
- Example chips: `Apa isi RUU Ketenagakerjaan yang baru disahkan?` · `Bagaimana kinerja IHSG pekan ini?` · `Apa kata OJK soal kredit perbankan?`

**Filters**
- `Topik` (`Semua topik`), `Portal` (`Semua portal`).
- `Tanggal`: chips `7 hari` · `30 hari` · `Pilih tanggal`, revealing `Dari` / `Sampai`.

**Loading:** `Mencari artikel yang relevan…` → `Menyusun jawaban dari {n} artikel…`

**Answer and sources**
- The answer's heading is the reader's question.
- Disclosure: `Disusun AI dari artikel di bawah dan bisa keliru. Cek sumbernya untuk detail.`
- Sources header: `Berdasarkan {n} artikel`.
- Card: `[n] {Outlet} · {Hari, d Mmm yyyy}`, then the headline, then `Baca di {Outlet} →`.

**Follow-up:** `Tanya lanjutan tentang topik ini…`; reset `Pertanyaan baru`.

**States**
- No hits: `Belum ada artikel yang membahas ini. Coba kata lain atau perluas rentang tanggal.`
- Narrow filters: `Tidak ada artikel {topik} dari {portal} pada {rentang}.` + `Hapus filter`.
- AI unavailable: `Ringkasan AI sedang tidak tersedia. Berikut artikel yang paling relevan dengan pertanyaan Anda.`
- Transient failure: `Jawaban gagal disusun. Artikel yang relevan tetap tersedia di bawah.` + `Coba lagi`.
- Number not verified: `Sebagian angka belum terverifikasi; cek sumbernya.`

## Answer prompt (SYS-99)
```
Kamu redaktur yang menjawab pertanyaan pembaca hanya dari artikel bernomor di bawah.
Hari ini {hari_ini}.

Aturan:
- Kalimat pertama langsung menjawab. Lalu paling banyak 3 poin pendukung. Total maks. 120 kata.
- Setiap fakta diberi nomor artikelnya, mis. [2] atau [1][3]. Jangan tulis nama portal atau tanggal sebagai kutipan.
- Salin angka persis seperti di artikel. Sebut tanggal kejadian (mis. "Senin, 5 Oktober"), bukan "kemarin".
- Teks biasa: tanpa Markdown, tanpa tebal, poin diawali "- ".
- Jangan sebut "konteks", "artikel yang diberikan", atau "sebagai AI".
- Jika artikel tidak cukup, tulis persis: "Artikel yang ada belum cukup untuk menjawab ini dengan pasti." lalu sebut apa yang memang dikatakan artikel.
- Riwayat percakapan hanya untuk memahami rujukan ("itu", "perusahaan tadi"), bukan sumber fakta.

Artikel:
[1] Kontan · Senin, 5 Okt 2026 · {judul}
{cuplikan}
...

Riwayat: {riwayat}
Pertanyaan: {pertanyaan}
```

## Out of scope
- A knowledge-base browsing page (entities): asked about 2026-10-07, not requested as a build.
- SYS-91 (1970 dates in FAISS) stays in its own queue.
