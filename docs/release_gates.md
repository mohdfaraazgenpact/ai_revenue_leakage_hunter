# Release Gates

A gate is **Met** only when its evidence can be re-run. Status as of 2026-10-19 (branch `ai_revenue_leakage_hunter_v3_claude_backend`). Numbers come from `vetting/results.json` and the generated README results block.

| Gate | Acceptance criteria | Status | Evidence / what is left |
|---|---|---|---|
| Financial correctness | All deterministic calculation tests pass, including simple/compound escalation, amendments, discounts, currencies and rounding | **Met, pending sign-off** | `tests/test_price_schedule.py`, `tests/test_reconcile.py`; vetting FIN-01..15 pass. Rounding rule and compounding default still need Mentor 1 (B-003); FX policy is open, so mismatches go to review (B-007) |
| Data integrity | Invalid rows are quarantined; duplicates and inconsistent line amounts cannot inflate exposure silently | **Met** | `src/reconcile.py` rules + `input_issues.csv`; vetting EXT-02..05, FIN-14, FIN-15, OPS-03 pass; overlay scenarios in the synthetic data are handled end to end (`tests/test_end_to_end.py`) |
| Ground truth | Every synthetic scenario has independently checked expected terms, amounts and labels | **Partly met** | Generator truth is event-driven and separate from the engine; hand-computed boundary tests added. Still needs Mentor 1 review of scenarios and expected outcomes (B-006, B-009) |
| Evaluation | Blind contract-level holdout; defined precision/recall, dollar-weighted metrics and false-positive exposure | **Not met** | Metrics are defined and separated (`src/evaluate.py`, vetting EVAL-01/02 pass). No blind holdout yet (EVAL-04, B-005) |
| AI comparison | Actual AI run, reproducible rules-vs-AI comparison and evidence-quality review | **Partly met (development set)** | Claude via Claude Code (D-020): field accuracy 100% vs 94.1% rules; 311/311 leakage lines, $0 false overbilling; 106/106 quotes verified (AI-01, AI-02 pass); identical results when replayed offline from the cache. Still open: Mentor 2 confirms scripted licence use (B-001); human spot check of citations; ambiguous-clause and prompt-injection tests (AI-03, AI-04); blind holdout (EVAL-04) |
| UI and claims | Exportable findings, clear uncertainty, human approval, no unsupported recovery claims | **Met, pending walkthrough** | UX-02, UX-03 pass; oracle banner, review queue, simulated value calculator. Finance-reviewer and new-user walkthroughs open (UX-01, UX-04) |
| Reproducibility | Clean setup, deterministic generation, automated tests, versioned evaluation artefacts | **Met** | Fixed seed and pinned document timestamps; README results generated with dataset fingerprint + commit; pytest and pre-commit; clean-clone check OPS-01 |

**Before the jury quotes any AI number:** the Evaluation and AI comparison gates must be met.
