# Blocker Log

| # | Raised | Blocker | Needs | Owner | Status |
|---|---|---|---|---|---|
| B-001 | 2026-10-15 | Confirm that using the free Gemini API with synthetic data is acceptable under Genpact policy | A yes/no decision | Mentor 2 | Open |
| B-002 | 2026-10-15 | Gemini API key not yet created or added to `.env`, so the smoke test has not run against the live API | The builder creates a key at aistudio.google.com and runs `.\scripts\tasks.ps1 smoke` | Builder | Open |
| B-003 | 2026-10-15 | Escalation rounding: round per step or at the end (D-004), and the default when a contract does not state compounding vs simple (D-010) | A rule decision | Mentor 1 | Open |
| B-004 | 2026-10-15 | Gemini extraction accuracy not yet measured. The extractor, prompt (v2), citation verifier and guardrails are built and tested offline with a fake LLM; the real numbers need the key (B-002). Then run `.\scripts\tasks.ps1 all` | Gemini key | Builder | Open |
| B-005 | 2026-10-15 | Blind-test contracts (3-5) written in Mentor 1's own words, with independently adjudicated expected terms and findings, to put in `data/blind/`. Split by contract, never by invoice line. | Contract texts + answer key | Mentor 1 | Open |
| B-006 | 2026-10-15 | Mentor review of seeded scenarios and pricing rules: anniversary, compounding, amendment same-day rule, discount rounding (see `docs/decisions.md`) | Sign-off | Mentor 1 | Open |
| B-007 | 2026-10-15 | FX policy for invoices in a currency other than the contract's (rate source, rate date, rounding). Until then they go to REVIEW (D-013). | A rule decision | Mentor 1 | Open |
| B-008 | 2026-10-15 | Validate the recoverability model (claim periods, dispute windows) or keep it labelled illustrative (D-019) | Finance/legal input | Mentor 1 | Open |
| B-009 | 2026-10-15 | Review the new integrity scenarios and their expected outcomes (credit notes, returns, duplicates, currency, malformed rows) and the adjustment sign conventions (D-012) | Sign-off | Mentor 1 | Open |
