# PM: QA + senior ticket list, 2026-10-12

- **Reader-visible effects:**
  - follow-ups that change subject are answered on the new subject (SYS-104);
  - "minggu ini" questions cite this week's articles when the week has them (SYS-138);
  - "sekarang" questions are not led by passing mentions (SYS-112).
- **Trade-off accepted:** a follow-up's cards appear ~1-3 s later (one rewrite call). The search box and first questions are unchanged.
- **Not in scope:** showing the reader "searched as: …" for a rewritten follow-up. It is logged only; revisit if readers are confused.
- **Success:** the Done-when lines of SYS-104 (QA-amended), SYS-138 and SYS-112, measured with the probes named in the spec.
