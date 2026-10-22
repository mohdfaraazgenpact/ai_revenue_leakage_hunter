# Revenue Leakage Hunter — Jury Storyline

*Contract intelligence · Deterministic reconciliation · Evidence-backed investigation*

**The problem.** Contract pricing, escalation clauses and amendments can drift away from what is actually billed. The resulting exceptions are hard to detect consistently at scale.

**Opportunity sizing.** To size the opportunity, we use a deliberately conservative 1% assumption against addressable annual billings. Published estimates are higher: MGI Research reports revenue leakage of at least 3–5%, while WorldCC reports losses associated with poor contract management of around 9%. These studies use broader definitions and different measurement bases, so we do not treat them as direct benchmarks for our solution. Our 1% is a planning assumption for a price-leakage use case, which we will validate through a controlled pilot. (Sources and caveats: app Home page, "Sources and caveats".)

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
- 100 automated tests and a 43-case vetting checklist.
- On the development set, Claude reads every key contract field correctly, where the rules baseline reads 94.1%, so the engine finds all seeded leakage with no false overbilling. Every quote it cites is verified in the document.

Figures: README "Current results", which is generated from the run.

**What is not proven yet.**
- Performance on contracts the system has never seen. The development-set AI result comes from the same generator as the test documents; the blind holdout (B-005) is not built yet.
- Behaviour on deliberately ambiguous or manipulated contract text (AI-03, AI-04).
- Real-world recovery. The recoverability figure and the value calculator are illustrative.

**What comes next.**
1. Get mentor sign-off on the pricing and data-integrity rules.
2. Build the blind benchmark.
3. Measure AI's added value over rules: accuracy, evidence quality, review rate and cost.
4. Run a controlled pilot on authorised data.

**Do not say:** "recovered", "found $X of revenue" as fact, or any AI accuracy figure until the AI comparison gate in `docs/release_gates.md` is met.
