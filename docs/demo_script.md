# Mentor Demo Script: Current Synthetic Data

Every input below is a real record in this repository's synthetic dataset (`data/contracts/`, `data/invoice_lines.csv`, `data/billing_adjustments.csv`). Figures come from the current run (Claude extraction, dataset fingerprint `cca8a43cec67`). If the data is regenerated, re-check them.

The app has no contract upload or manual invoice entry. "Load" means selecting the record in the app. The only live edit is the escalation clause in **Leakage Analysis → What-if: change a contract**.

**Before the meeting**
- Start the app: `.\scripts\tasks.ps1 app`. Sidebar: *Contract terms from* = Claude extraction (AI).
- For Scenario C (step 2) and Scenario B (step 4), switch **Offline demo mode off**. In offline mode the What-if tab uses the rules reader, which misses the wording and the ambiguity tests. The exact clause texts below are already cached, so they replay instantly.
- To start from a clean Review Queue, delete `data/output/review_decisions.csv`.

## Run order (about 8 minutes)
| # | Step | Record | Time |
|---|---|---|---|
| 1 | Clear underbilling | C-2008 / IL-00349 | 2 min |
| 2 | Change a contract term and rerun | C-2020 | 2 min |
| 3 | Review queue: data exceptions and an unsupported credit | IL-00801, IL-D0002, F-022 | 1–2 min |
| 4 | Ambiguous contract → review, not a guess | C-2020 edited | 1 min |
| 5 | Benchmark results and mentor decisions | reports | 1–2 min |

---

## 1. Scenario A: Clear underbilling

**Contract:** C-2008, Nimbus Edge Devices Inc (CU-108), `data/contracts/C-2008.docx`, Hi-Tech
- Price clause A.1: *"HTC-2003 - Software subscription per seat: USD 235.75 per unit."*
- Escalation clause 4.2: 3.5% compounding from the first anniversary (1 April 2025). The invoice below predates it, so the base price applies.

**Invoice line:** IL-00349

| Field | Value |
|---|---|
| Invoice ID | INV-2008-202404 |
| Invoice date | 2024-04-15 |
| Contract / Customer | C-2008 / CU-108 |
| SKU | HTC-2003 |
| Currency | USD |
| Quantity | 447 |
| Contract unit price | $235.75 |
| Billed unit price | $226.32 |
| Expected line value | $105,380.25 |
| Billed line value | $101,165.04 |
| **Potential underbilling** | **$4,215.21** |

Calculation: (235.75 − 226.32) × 447 = 9.43 × 447 = **$4,215.21**.

The same price gap repeats on 21 lines (April 2024 – December 2025), and from April 2025 it compounds with the escalation. Finding **F-001**: Price below contract, **$96,562.09** potential underbilling.

**Clicks:** Leakage Analysis → Prioritised findings → *Open finding* "F-001 · Nimbus Edge Devices Inc · HTC-2003 · Price below contract".
Show the contract-vs-billed price chart, the clause A.1 quote (verified ✓), the calculation, and IL-00349 in *Affected invoice lines*. Then Contract evidence → C-2008 to show the highlighted clause in the document.

**Recommended action (from the app):** Correct the unit price in the price master; check with the account owner that no undocumented concession exists before preparing a rebill. Owner: Billing Operations & Sales Operations.

**Ask the mentor:** "Can a Finance analyst reproduce this from clause A.1 and invoice line IL-00349 without trusting the AI's explanation?"

## 2. Scenario C: Change a contract term and rerun

**Contract:** C-2020, Helix Arc Robotics LLC (CU-120), `data/contracts/C-2020.docx`
- Price clause A.1: HTC-2003 at **USD 201.25** per unit.
- Escalation clause 4.2: *"On 1 January 2025 and on each anniversary of that date thereafter, the Unit Prices shall increase by 3%."*
- Every invoice is billed at $201.25, so the 2025 escalation was missed.

**Before and after the escalation date (SKU HTC-2003):**

| | IL-01049 (before) | IL-01051 (after) |
|---|---|---|
| Invoice | INV-2020-202412 | INV-2020-202501 |
| Date | 2024-12-05 | 2025-01-05 |
| Quantity | 364 | 325 |
| Contract price applicable | $201.25 (base) | $207.29 (201.25 × 1.03) |
| Billed price | $201.25 | $201.25 |
| Status | MATCH, $0 | Potential underbilling, **$1,963.00** (6.04 × 325) |

The invoice before 1 January 2025 correctly uses the base price.

**Live edit:** Leakage Analysis → What-if: change a contract → Contract **C-2020**. Paste each clause, then click *Re-read contract and re-run hunt*. Results are for both C-2020 SKUs combined (HTC-2002 and HTC-2003):

| Edit the clause to | Read as | Leakage before → after |
|---|---|---|
| `On 1 January 2025 and on each anniversary of that date thereafter, the Unit Prices shall increase by 5%.` | 5% | $48,705.80 → **$81,147.50** |
| `On 1 January 2026 and on each anniversary of that date thereafter, the Unit Prices shall increase by 3%.` | 3% from 2026 | $48,705.80 → **$0** (no 2025 invoice is affected) |
| `On 1 January 2025 and on each anniversary of that date thereafter, the Unit Prices shall increase by five percent.` | 5% (Claude) | $48,705.80 → **$81,147.50** |

The last row is the "why AI" moment. The rules reader misreads "five percent" as no escalation ($0); Claude reads it as 5%.

## 3. Review queue: data exceptions and an unsupported credit
**Clicks:** Review Queue → *Data exceptions (5)*.

| Line | Invoice | Contract / SKU | Issue | Why flagged | What is missing | Next step |
|---|---|---|---|---|---|---|
| IL-00801 | INV-2015-202403 (2024-03-25) | C-2015 Keystone Parcel Services / LOG-3001 | `CURRENCY_MISMATCH` | Invoiced in **EUR** at 2,447.25 × 22; contract is in USD | An approved FX rate and conversion policy | Analyst confirms the currency and FX policy before any comparison |
| IL-D0002 | INV-2015-202405 (2024-05-25) | C-2015 / LOG-3001 | `POSSIBLE_DUPLICATE` | Same invoice, SKU, date, quantity (23) and amount as IL-00805, under a new line ID | Confirmation of whether two shipments were real | Analyst checks the shipment record; void the line or confirm it |
| IL-00437 | INV-2010-202405 | C-2010 / MFG-1005 | `INVALID_INPUT` | Date `20/05/2024` is not YYYY-MM-DD | A valid invoice date (it decides which price applies) | Fix the source row and rerun |

Also shown: IL-D0001 (possible duplicate of IL-00088), IL-01023 (blank line amount), and 2 exact duplicates excluded from totals.

**Unsupported credit (a finding, not a data exception):** F-022, Redfield Castings LLC, C-2010, MFG-1001.

| Line | Invoice | Credit note | Reason on the credit | Effect |
|---|---|---|---|---|
| IL-00427 | INV-2010-202403 (531 × $116.00) | ADJ-0012, $4,927.68, 2024-04-04 | "Goodwill credit - no approval reference" | Net billed below contract by $4,927.68 |
| IL-00443 | INV-2010-202407 (444 × $116.00) | ADJ-0011, $4,120.32, 2024-08-04 | "Goodwill credit - no approval reference" | Net billed below contract by $4,120.32 |

Total **$9,048.00**. The app's action: match each credit note to an approved credit request; if none exists, reverse the credit or document the approval.

**Optional decision demo:** Review Queue → Findings to validate → F-001 → *Validated - recovery justified* → Record decision. Business Impact then shows $96,562 under **Validated recovery opportunity**, while **Cash actually recovered** still reads *Requires pilot*.

**Message:** none of these lines is a confirmed loss. The system prioritises investigation and refuses to compute money it cannot support.

## 4. Scenario B: Ambiguous contract → review, not a guess
Use the What-if tab on **C-2020** with Offline demo mode **off**. Paste:

```
The Supplier may adjust Unit Prices annually based on the applicable inflation index, subject to the commercial terms agreed by both parties. The applicable index, adjustment percentage, effective date and any cap must be confirmed in the mutually signed commercial schedule.
```

What Claude does (tested 2026-10-22):
- Reads an inflation-linked escalation, but escalation confidence drops to **0.4**.
- Raises the issue *"escalation without a first escalation date"*.
- Routes all **48** C-2020 invoice lines to review (`TERMS_NOT_DETERMINABLE`). The app shows "Lines sent to review: 48".
- Leakage after the edit shows **$0** because nothing can be priced safely, not because the invoices match.

What to say: the system does not invent a rate or a date. It names the missing information (index, percentage, effective date, cap from the signed commercial schedule) and hands the case to an analyst.

Caveat: with the rules reader (offline mode) the same text is misread as "no escalation" and nothing goes to review. That is another reason the AI reader matters, and why the blind holdout must include ambiguous wording (AI-03).

## 5. Benchmark results (development set)
**Clicks:** Technical Architecture → *AI vs rules* and *Evaluation scorecard*.

| Metric | Rules baseline | Claude (`claude-sonnet-5-5`) |
|---|---|---|
| Key contract fields read correctly | 94.1% (21/30 contracts fully correct) | 100% (30/30) |
| Seeded leakage lines detected | 222/311 (71.4%) | 311/311 |
| Leakage $ found vs $757,338 seeded | $499,409 (34.1% error) | $757,338 (0.0% error) |
| False overbilling exposure | $139,908 | $0 |
| Lines sent to review | 335 | 5 |
| Evaluation gate | FAIL | PASS |

> "The rules baseline misses some seeded leakage and produces false overbilling exposure on this dataset. The Claude-backed version performs substantially better on the same development set. Our next milestone is a blind test on unseen contracts, with agreed acceptance criteria, before making broader performance claims."

These are synthetic development-set results from the same generator the rules were built against, not independent validation. Do not present them as 100% accuracy on unseen contracts.

**Mentor decisions to ask for:**
1. Blind holdout: Mentor 1 writes 3–5 unseen contracts with an answer key (B-005), with thresholds agreed in advance.
2. Finance rules: rounding/compounding default, FX policy, adjustment signs, recoverability (B-003, B-007, B-008).
3. Governance: confirm scripted Claude use for synthetic data (B-001).
4. Sign-off on the Home page and journey (plan v9 review questions R1–R5).
