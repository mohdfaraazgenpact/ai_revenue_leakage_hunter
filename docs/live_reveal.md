# Live Reveal: One Case, Four Reveals (about 2 minutes)

The on-stage demo for the showcase (plan v10). One discrepancy carries the whole story, from contract to cash. The full mentor walkthrough is in `docs/demo_script.md`.

Every figure below comes from the current synthetic run (Claude extraction, dataset fingerprint `cca8a43cec67`). Re-check them if the data is regenerated.

**Before going on stage**
- Start the app: `.\scripts\tasks.ps1 app`. Sidebar: *Contract terms from* = Claude extraction (AI). Offline demo mode **on** (no live AI call is needed for this sequence).
- Delete `data/output/review_decisions.csv` so Finance validated reads $0 and F-003 reads *Awaiting review*.
- Open the app on **Home**.

## Opening line (before touching the screen)
> "The contract says one thing. The invoice says another. The cash never tells you why. The question isn't just *what did we invoice*. It's *what should we have invoiced, and what happened to the difference?*"

## Reveal 1: The entitlement hidden in the contract (30 s)
**Screen:** Home → *Priority case*, then **Open evidence** → *Contract evidence* tab → C-2003, page 4.

Meridian Freightways Inc, contract C-2003, service LOG-3003 (last-mile parcel delivery). Three clauses on three different pages:

| Clause | Page | Says |
|---|---|---|
| A.1 | 3 | Base price USD 11.25 per unit |
| 4.2 | 1 | +2.5% each 1 June, from 1 June 2025, written as *"two and one-half percent (2.5%)"* |
| **AM1.1** | **4** | **From 29 September 2024, the price is USD 12.00** |

> "The amendment is on page 4. Billing never loaded it."

**Reaction we want:** "I can see why this is hard to find at scale."

## Reveal 2: The financial discrepancy (30 s)
**Screen:** *Prioritised findings* → F-003 (opened by the button): price chart, clause quotes, calculation, affected lines.

| | IL-00151 | IL-00153 | IL-00169 |
|---|---|---|---|
| Invoice date | 2024-09-25 | 2024-10-25 | 2025-06-25 |
| What applies | Base price (before the amendment) | Amendment | Amendment + 2.5% escalation |
| Contract price | $11.25 | $12.00 | $12.30 |
| Billed price | $11.25 | $11.25 | $11.53 |
| Result | Match, $0 | **$5,361.00** (0.75 × 7,148) | **$5,289.90** (0.77 × 6,870) |

The September invoice predates the amendment and is correctly a match. From June 2025, billing *did* apply the escalation, but to the old price (11.25 × 1.025 = 11.53). The amendment was missed, so every escalation now compounds the gap.

**Total:** 15 invoices, Oct 2024 to Dec 2025, **$82,107.94** potential underbilling. Calculation shown: `USD 12.00 (AM1) x (1 + 2.5%) [2025-06-01] = USD 12.30`.

> "Every number is one click from the clause and the invoice line. The AI read the contract; plain arithmetic calculated the money."

**Reaction we want:** "I can see exactly what was missed and why."

## Reveal 3: It knows when to stop (20 s)
**Screen:** Review Queue → *Data exceptions*.

IL-00801, invoice INV-2015-202403, contract C-2015: invoiced in **EUR** (22 × 2,447.25), contract in **USD**. Status REVIEW, *"no FX conversion policy is configured."* No leakage figure is produced.

> "It doesn't guess an exchange rate. No approved FX policy, no number. A person decides."

Optional, only if the live AI call is available and Offline demo mode is off: the ambiguous inflation clause on C-2020 (demo script, Scenario B) sends all 48 lines to review instead of inventing a rate.

**Reaction we want:** "This is built for financial control, not just AI answers."

## Reveal 4: The business outcome (30 s)
**Screen:** Review Queue → *Findings to validate* → F-003 → *Validated - recovery justified* → **Record decision**. Then Home.

- The recovery panel appears: Validated opportunity $82,108 · Billing correction: draft note ready · Receivable: Not yet tracked · **Cash recovered: Not yet tracked**.
- Home: *Finance validated* moves from $0 to **$82,108**. *Cash recovered* still reads **Not yet tracked**.

> "Detected is not validated, and validated is not cash. Today the prototype covers detection and Finance validation. Rebilling, receivables and cash receipt are the target operating model we take into a pilot."

## Closing line
> "The breakthrough isn't another dashboard that reports what happened. It's connecting what the business was entitled to earn with what it billed, and giving Finance the evidence to act on the difference."

## Do not say
- "Recovered" or "found $X of revenue" as fact. Everything shown is synthetic and unvalidated.
- That existing Finance platforms (Finance One, AP Suite) cannot do this, until their owners have confirmed what they do (plan v10, D1–D5).
- Any AI accuracy figure beyond "development set, not blind".
