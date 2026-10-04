# QA decisions — index

## Cross-cutting principles
- Repo workflow (CLAUDE.md): dev implements and labels `status: ready-for-qa`; only QA closes or sends back. QA files every ticket that comes from testing.
- Verify independently of dev's evidence: suites, own mutants (`PYTHONDONTWRITEBYTECODE=1`), read-only live checks, scheduled-run evidence.
- No production DB writes without asking the owner.
- One ticket per finding; never park findings as comments on umbrella tickets.

## Active features
- [qa-pass-2026-10-04](qa-pass-2026-10-04.md) — verify the 9 ready-for-qa tickets (spec: `.10x/specs/2026-10-04-qa-verification-pass-design.md`)
- [p1-p2-newsletter-fixes](p1-p2-newsletter-fixes.md) � audit of OPS-20/SYS-68/SYS-67/SYS-63: nothing closed; SYS-71 P2 blocks, 3 P3s filed (2026-10-04)
