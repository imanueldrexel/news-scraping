# Staff engineer: dev fixes of QA's second pass (2026-10-12)

- **One tokenizer.** Any "does this paragraph hold word X" test goes through `QueryProcessor._word_tests` (`to_tsvector('simple')`), never a Python split. `_coverage` and the FTS already do this.
- **A gate, not a filter.** A hit that fails the gate is ranked normally, never dropped. The floor stays the only filter (ADR-006/007).
- **Test seams.** The `_qp` helper stubs every DB-backed method. The new `_holds_subject` gets a stub parameter whose default is "holds", so existing window tests keep their meaning. New tests pass it explicitly.
- **Word lists** (`_NOT_REFERENCES`, refusal openers) are module constants with a comment naming the ticket, with one test per entry class, not per word.
- **Scripts never import scripts** (ADR-015). A unit test scans `scripts/*.py` for `import <another script>`.
- **Hygiene test (DBT-68)** uses `ast`, scoped to `tests/**/test_*.py`. It reports file, name and count.
