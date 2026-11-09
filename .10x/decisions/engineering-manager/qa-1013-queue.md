# Engineering Manager — QA's 2026-10-13 queue (2026-10-19)

Order: deterministic measurement first, then the shared module, then its two users; the small tickets fill in.

1. **SYS-194** (#396): ORDER BY unique last key + unit test; replay twice. 0.5 h.
2. **SYS-144 + SYS-145** (#327/#328), ADR-021 decisions 1-2: `nya_words.py`, `refers_to_thread`, `resolve`; unit tests
   + QA file; mutants; `measure_name_gate.py` and QA's probes on the real code. 2 h.
3. **SYS-146** (#331), ADR-021 decision 3: `terms` root/adverb; unit test (same anchors); `measure_nya_terms.py`,
   replay. 1 h.
4. **DBT-60** (#258): numeric forms; unit + QA file; mutants. Crawl-imported: green before 06:45 or after 07:00's run.
   0.5 h.
5. **DBT-70** (#332): `store_repair.sitemap_state`; test; integration suite (it is a store check). Crawl-imported,
   same rule. 0.5 h.
6. **DBT-71** (#334): two tests; QA's two mutants KILLED. 0.25 h.
7. **SRC-62** (#333): re.match, deny `money-lab`; unit test; `check_crawlers.py --website INVESTORID`. 0.5 h.
8. Suites (unit + integration), EXPERIMENTS.md entries, ticket comments + `status: ready-for-qa`, state files.

Risks: the replay moving under SYS-146's roots (measured, not assumed); the 07:00 crawl window.
Not in scope: SYS-195 (#397), the re-label of INVESTORID's 90 stored money-lab rows (a production write; the owner
decides).
