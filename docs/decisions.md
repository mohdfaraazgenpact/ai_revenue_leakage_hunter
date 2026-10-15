# Decision Log

| # | Date | Decision | Rationale | Owner |
|---|---|---|---|---|
| D-001 | 2026-10-15 | MVP covers only contracted vs. invoiced price, including missed escalations and amendments not applied | One leakage type done well is credible for a 1-builder, 10-day PoC | Builder + both mentors |
| D-002 | 2026-10-15 | The LLM reads and writes language only. All money arithmetic is deterministic Python (Decimal, ROUND_HALF_UP to cents). | Prevents hallucinated amounts, keeps every $ auditable | Mentor 2 |
| D-003 | 2026-10-15 | LLM = free Google Gemini API, synthetic data only, accessed through the `LLMClient` interface with a disk cache | Free and available now. The cache handles rate limits and the offline demo. Swappable for a pilot. | Mentor 2 (policy sign-off pending) |
| D-004 | 2026-10-15 | Escalation compounds on each anniversary on or after `first_escalation_date`. Compounding is exact, and the unit price is rounded to cents once (current `expected_unit_price()` behaviour). | Simple and auditable. *Mentor 1 to confirm rounding once vs. after each step.* | Mentor 1 |
| D-005 | 2026-10-15 | Underbilling and overbilling are reported separately and never netted | Netting hides leakage | Mentor 1 |
| D-006 | 2026-10-15 | Every extracted value needs a verbatim quote verified against the document. Otherwise it goes to the review queue. | Trust and explainability | Mentor 2 |
| D-007 | 2026-10-15 | An amendment price applies from its effective date. Escalations continue on later anniversaries. A same-day anniversary is treated as already included in the amended price. | Avoids double escalation. Matches the amendment wording in the synthetic contracts. | Mentor 1 |
| D-008 | 2026-10-15 | An approved discount is applied to the escalated, rounded unit price, then rounded again | Matches how billing systems apply line discounts | Mentor 1 |
| D-009 | 2026-10-15 | The rules extractor is kept as an honest baseline, not tuned to every wording variant | The AI vs. rules comparison must be credible to the jury | Mentor 2 |
