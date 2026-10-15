# Revenue Leakage Hunter — Jury Storyline

*Contract intelligence · Deterministic reconciliation · Evidence-backed investigation*

**The problem.** Contract pricing, escalation clauses and amendments can drift away from what is actually billed. The resulting exceptions are hard to detect consistently at scale.

**The innovation.** A hybrid system extracts contract terms and reconciles them against invoice records. It quantifies potential discrepancies and shows the source evidence for human review.

**Why AI.** Contract language varies and depends on context. AI can interpret clauses that rules miss, such as relative dates and rates written in words. Deterministic calculation keeps every dollar traceable.

**What makes it trustworthy.**
- Every finding is tied to a contract clause, an invoice line and a calculation.
- Underbilling and overbilling are never netted.
- Lines the engine cannot price safely go to a review queue and are never counted as matches. This covers invalid input, duplicates, currency mismatches, inconsistent invoice arithmetic, unsupported adjustments and contract terms it cannot determine.
- Answer-key runs are labelled as oracle checks and cannot be mistaken for detector results.

**What is proven today.**
- A working synthetic-data prototype.
- A money engine that matches the answer key exactly when the contract terms are right.
- A rules baseline measured on the same documents.
- 64 automated tests and a 43-case vetting checklist.

Figures: README "Current results", which is generated from the run.

**What is not proven yet.**
- Whether Gemini beats the rules baseline. The integration is built but not benchmarked, because there is no API key or policy sign-off yet.
- Performance on contracts the system has never seen. The blind holdout is not built yet.
- Real-world recovery. The recoverability figure and the value calculator are illustrative.

**What comes next.**
1. Get mentor sign-off on the pricing and data-integrity rules.
2. Build the blind benchmark.
3. Measure AI's added value over rules: accuracy, evidence quality, review rate and cost.
4. Run a controlled pilot on authorised data.

**Do not say:** "recovered", "found $X of revenue" as fact, or any AI accuracy figure until the AI comparison gate in `docs/release_gates.md` is met.
