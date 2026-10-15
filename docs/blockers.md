# Blocker Log

| # | Raised | Blocker | Needs | Owner | Status |
|---|---|---|---|---|---|
| B-001 | 2026-10-15 | Confirm that using the free Gemini API with synthetic data is acceptable under Genpact policy | A yes/no decision | Mentor 2 | Open |
| B-002 | 2026-10-15 | Gemini API key not yet created or added to `.env`, so the smoke test has not run against the live API | The builder creates a key at aistudio.google.com and runs `.\scripts\tasks.ps1 smoke` | Builder | Open |
| B-003 | 2026-10-15 | Escalation rounding: round per step or at the end (D-004) | A rule decision | Mentor 1 | Open |
| B-004 | 2026-10-15 | Gemini extraction accuracy not yet measured. The extractor, prompt, citation verifier and guardrails are built and tested offline with a fake LLM; the real numbers need the key (B-002). Then run `.\scripts\tasks.ps1 all` | Gemini key | Builder | Open |
| B-005 | 2026-10-15 | Blind-test contracts (3-5) written in Mentor 1's own words, to put in `data/blind/` | Contract texts | Mentor 1 | Open |
| B-006 | 2026-10-15 | Mentor review of seeded scenarios and pricing rules: anniversary, compounding, amendment same-day rule, discount rounding (see `docs/decisions.md`) | Sign-off | Mentor 1 | Open |
