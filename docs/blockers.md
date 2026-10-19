# Blocker Log

| # | Raised | Blocker | Needs | Owner | Status |
|---|---|---|---|---|---|
| B-001 | 2026-10-15 | Confirm policy for the LLM. Updated 2026-10-19: the backend is now Claude via Claude Code headless mode on the builder's licence (D-020). Confirm that scripted (`claude -p`) use with synthetic data only is permitted, and any restrictions | A yes/no decision | Mentor 2 | Open |
| B-002 | 2026-10-15 | Gemini API key not yet created or added to `.env`, so the smoke test has not run against the live API | The builder creates a key at aistudio.google.com and runs `.\scripts\tasks.ps1 smoke` | Builder | Closed 2026-10-19: superseded by the Claude backend (no key needed); smoke test passed live |
| B-003 | 2026-10-15 | Escalation rounding: round per step or at the end (D-004), and the default when a contract does not state compounding vs simple (D-010) | A rule decision | Mentor 1 | Open |
| B-004 | 2026-10-15 | Gemini extraction accuracy not yet measured. The extractor, prompt (v2), citation verifier and guardrails are built and tested offline with a fake LLM; the real numbers need the key (B-002). Then run `.\scripts\tasks.ps1 all` | Gemini key | Builder | Closed 2026-10-19: measured with Claude on the development set (README results, `reports/evaluation_llm.md`). Blind-set accuracy remains under B-005 |
| B-005 | 2026-10-15 | Blind-test contracts (3-5) written in Mentor 1's own words, with independently adjudicated expected terms and findings, to put in `data/blind/`. Split by contract, never by invoice line. | Contract texts + answer key | Mentor 1 | Open |
| B-006 | 2026-10-15 | Mentor review of seeded scenarios and pricing rules: anniversary, compounding, amendment same-day rule, discount rounding (see `docs/decisions.md`) | Sign-off | Mentor 1 | Open |
| B-007 | 2026-10-15 | FX policy for invoices in a currency other than the contract's (rate source, rate date, rounding). Until then they go to REVIEW (D-013). | A rule decision | Mentor 1 | Open |
| B-008 | 2026-10-15 | Validate the recoverability model (claim periods, dispute windows) or keep it labelled illustrative (D-019) | Finance/legal input | Mentor 1 | Open |
| B-009 | 2026-10-15 | Review the new integrity scenarios and their expected outcomes (credit notes, returns, duplicates, currency, malformed rows) and the adjustment sign conventions (D-012) | Sign-off | Mentor 1 | Open |
| B-010 | 2026-10-19 | The explanation guardrail treats every number in the AI narrative as a money fact. In the first Claude run it blocked 8 of 24 narratives (they fell back to the template) because of step numbers "(2)", page references and invoice-line counts, not wrong amounts. Decide whether to allow-list these, or keep it strict | A decision on guardrail scope (fail-safe today) | Mentor 2 | Open |
