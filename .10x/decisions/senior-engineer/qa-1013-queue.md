# Senior Engineer — QA's 2026-10-13 queue (2026-10-19)

- **nya_words.py:**
  - `ADVERBS` holds the 22 existing ones, QA's 6 (sebaiknya, sebetulnya, nantinya, sayangnya, secepatnya, sepenuhnya),
    and those from the mined list (`sys144/mine_nya_adverbs.py`) with no referent in a question: menariknya,
    ironisnya, pasalnya, faktanya, nyatanya, kenyataannya, idealnya, sejatinya, pastinya, tadinya, mulanya, awalnya,
    kabarnya, makanya, tepatnya, istilahnya, jadinya, sedikitnya, selengkapnya, untungnya, kiranya, sekiranya,
    sepatutnya, selayaknya, seyogianya.
  - **Kept as references** (they point back in a question): akibatnya, sebaliknya, karenanya, artinya, hasilnya,
    intinya, rencananya, alasannya, dampaknya, menurutnya, sesudahnya, setelahnya, utamanya ("tujuan utamanya"),
    rasanya ("bagaimana rasanya").
  - `possessive_root(word)`: lower, ends in "nya", not in ADVERBS/NOT_CLITIC, root = word[:-3].rstrip("-"), len >= 3,
    else None.
- **followup:**
  - `_REFERENCE` stays; its -nya alternative is judged by `nya_words`.
  - `refers_to_thread(q, previous)`:
    - refs = start offsets of the reference words;
    - none → False;
    - `own = names(q) - vocabulary(thread)`;
    - remove the names found only inside object phrases, unless they stand before the last reference
      (`names(q[:last_ref])`);
    - return `not own`.
  - A name both inside and outside an object phrase counts.
- **keywords.terms:**
  - after the stopword checks, `nya_words.possessive_root(low)` replaces `low`;
  - an ADVERBS word is skipped;
  - the name flag is computed on the word as written.
- **SYS-194:** append `, c.chunk_id DESC` after ts_rank_cd (both the plain and the recent ORDER BY).
- **DBT-60:** a bool or datetime passes; a `numbers.Real` → `Decimal(str(value))`; a str → stripped, `Decimal(s)`
  in a try (InvalidOperation = not numeric → pydantic). Integral with 8 digits → strptime; anything else numeric →
  ValueError. numpy is not imported by the DTO (`numbers.Real` covers its scalars).
- **SRC-62:** a section regex `^https://investor\.id/([a-z-]+)/\d+/` with `re.match`; return group 1 or None.
