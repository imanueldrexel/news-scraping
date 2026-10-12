# Security review (dev self-review, for QA): QA + senior list, 2026-10-12

Scope: commits 2ffdf28..454b6d0. No new endpoint, auth surface or secret.

| Change | Threat | Assessment |
|---|---|---|
| ADR-010 follow-up rewrite (`web/followup.py`) | **Prompt injection** through the follow-up or the thread ("abaikan instruksi…") | The output is only a search string. It is checked (one line, ≤ 300 chars), bound as SQL parameters (`keywords.lexeme` strips quotes and backslashes; every word is a bind value) and embedded. It is never rendered, executed or sent to the answer prompt: the answer still gets the reader's own text. Worst case: a reader's own follow-up retrieves odd cards for that reader. The prompt marks quoted text as data. **Accepted.** |
| ADR-010 | **Cost abuse** (a script hammering follow-ups) | Each call is counted under `web:<model>` and stops at `RAG_DAILY_COST_LIMIT_USD`, like the answer. ~$0.0001/call. One uvicorn worker, local network. **Accepted.** |
| ADR-010 | Thread data reaching a third party | The thread (the reader's questions) already went to the same provider in the answer prompt (ADR-005). Nothing new leaves. |
| ADR-010 logging | The rewritten question in the INFO log (≤ 200 chars) | Questions were already logged by the page; same personal deployment. |
| SYS-139 soft deadline | The job tuple between parent and child | Local `multiprocessing` pipe, same account. A float budget. No change in trust. |
| SYS-137 `drop_oversized_queued_chunks.py` | A destructive production write | Run lock (OPS-26 test), `started` crawl_log refusal, backup before any delete, vectors before rows, refusal on any entity mention. Dry run is the default. |
| SYS-137 store check | SQL | Fixed text, one bind value (`:m`). |

No finding.
