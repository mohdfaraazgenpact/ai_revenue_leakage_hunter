# AI Revenue Leakage Hunter: PoC Plan, v10 (Mentor 2: Finance Story and Live Reveal)

> **v10 change note**: responds to Mentor 2's feedback ("why are we doing it", "looks vanilla, lots of text", "complete end-to-end flow", "differentiation", "wow moment", "get a partner", "elevate the game"). Leads with the business problem, redesigns the Home page around three business measures and one priority case, adds a 2-minute four-reveal live demo, frames differentiation as a hypothesis to validate with Finance and the Finance One / AP Suite owners, and adds a partner workstream. The v9 feature freeze is lifted for the presentation layer only: the engine, rules, prompts and data are unchanged. Everything in v9 (1% wording, R1–R5 review, blind holdout) still applies.

## 1. Positioning
> AI Revenue Leakage Hunter bridges contractual entitlement and financial execution. It helps Finance identify what may have been missed, prove the discrepancy, and track whether corrective action results in recovered cash.

**Not:** "another AI dashboard", "a tool that finds invoice errors", or "we use AI to extract contract terms".

**Opening (problem first, AI second):**
> The contract says one thing. The invoice says another. The cash never tells you why. The question isn't just "what did we invoice?" It's "what should we have invoiced, and what happened to the difference?"

**Opportunity (illustrative scenario, not a client result):** $1B annual billings in scope × 1% assumed leakage = $10M gross opportunity *to investigate*.
> "We don't need to assume that all leakage is recoverable. We need a systematic way to discover the discrepancies, prove which ones are valid, and track the cases that result in additional billing and cash."

## 2. Feedback → action
| Mentor 2 feedback | Action | Status |
|---|---|---|
| Connect with Finance | Meet a Finance / O2C / AR or revenue-assurance stakeholder (section 6) | **Open**, user |
| "Why are we doing it?" | Problem-first opening on the Home page, jury storyline and live reveal | Done |
| "Looks vanilla, lots of text" | Home redesigned: hero, 3 KPIs, contract-to-cash strip, priority case, compact queue. Text cards, audience chips and the calculator are gone from the main view (the calculator is now in an expander) | Done |
| "Complete end-to-end flow" | Detected / Validated / Recovered states on Home, Flow page and Review Queue; recovery panel shown as target operating model | Done (recovery is target model, not live) |
| "Think of differentiation" | Bridge hypothesis (section 3) and questions D1–D5 for Finance One / AP Suite owners | **Open**, needs answers before any claim |
| "Wow moment" | `docs/live_reveal.md`: one case, four reveals, about 2 minutes | Done; rehearse |
| "Get a partner / more people" | Three partner roles (section 5) | **Open**, user |
| "Elevate the game" | 6-slide deck (section 7), UI and live reveal together | Deck open |

## 3. Differentiation: a hypothesis, not a claim
| Upstream: contract and commercial intelligence | The proposed bridge | Downstream: Finance execution and cash |
|---|---|---|
| What was agreed? Which price, escalation, surcharge, amendment and effective date apply? | AI interprets terms → deterministic logic checks amounts → evidence supports a Finance decision | What was invoiced? What is outstanding? Was the discrepancy corrected, disputed, recovered and paid? |

We do **not** claim existing platforms can't do this. Questions for the Finance stakeholder and the Finance One / AP Suite owners:

| # | Question | Answer |
|---|---|---|
| D1 | Which contract-to-billing checks are already automated? | |
| D2 | Can current systems interpret unstructured contract clauses and amendments, or do they rely on structured pricing data? | |
| D3 | Can they compare contractual entitlement with invoice-level actuals, with clause-level evidence? | |
| D4 | Do they identify missed billing entitlements, or mainly manage invoices, approvals, exceptions and payments? | |
| D5 | Where does the workflow break today, and how much manual effort does that create? | |

Slide 3 contrasts with existing systems only after D1–D5 are answered.

## 4. End-to-end flow: built vs target
| State | Meaning | In the PoC |
|---|---|---|
| **Detected** | The system found a possible discrepancy, with clause and invoice evidence | Built (Leakage Analysis) |
| **Validated** | Finance confirmed it is genuine and actionable | Built (Review Queue decision + audit log) |
| **Recovered** | The correction produced a reconciled cash receipt | Target operating model. Draft rebilling note only. Receivable and cash fields show "Not yet tracked" |

Cash recovered is never inferred from the validated amount.

**Live reveal** (`docs/live_reveal.md`), built on F-003, Meridian Freightways, C-2003 / LOG-3003:
1. **Entitlement:** amendment AM1.1 on page 4 raises the price to USD 12.00 from 29 Sep 2024.
2. **Discrepancy:** billing kept USD 11.25, then applied the 2.5% escalation to the old price (11.53 vs 12.30). 15 invoices, $82,107.94. The September invoice before the amendment correctly matches.
3. **Knows when to stop:** IL-00801 in EUR against a USD contract goes to review; no FX guess.
4. **Outcome:** validate F-003 → Finance validated $82,108; Cash recovered still "Not yet tracked".

## 5. Partners
| Role | Contribution | Ask |
|---|---|---|
| P1 Finance / O2C / AR | Business rules, real workflow, credibility, acceptance criteria | 30-min meeting (section 6); then review the live reveal |
| P2 Finance One / AP Suite owner | Capability comparison, data held, integration options | Answer D1–D5 |
| P3 AI / technology delivery | Architecture, model access, data governance, deployment, path from synthetic data to a controlled pilot | Review `docs/technical_architecture.md`; confirm B-001 |

Minimum: one Finance champion and one technology / delivery partner who actively review the solution. Any endorsement in the pitch must be genuine and agreed with that person.

## 6. Finance meeting
**Message:**
> Hi, I'm developing an AI-powered Revenue Leakage Hunter focused on Order-to-Cash and revenue assurance.
>
> The idea is to bridge the gap between what a contract entitles the business to bill and what is actually invoiced, helping Finance teams identify and validate potential missed revenue.
>
> I have a working synthetic-data PoC and am now validating the business workflow and differentiation against existing Finance platforms.
>
> I'd value 30 minutes to understand how these discrepancies are handled today, where the biggest gaps exist, and what evidence Finance would need to trust and act on a finding. Your input would help shape the solution around a real business need rather than a technology-led use case.

**Ask for:**
1. One anonymised or synthetic example of a real process failure.
2. The current resolution workflow (who finds it, who validates, how a rebill or credit is raised, how cash is matched).
3. A Finance-approved definition of a successful outcome.
4. Answers to D1–D5, or the name of the platform owner who can answer them.

Do not request confidential client contracts unless the right permissions are in place.

## 7. Pitch deck (6 slides)
| # | Slide | Content | Depends on |
|---|---|---|---|
| 1 | The revenue gap | "What we earn, what we bill, and what we actually collect can be three different numbers." One contract-to-cash visual | |
| 2 | The opportunity | $1B × 1% = $10M, labelled illustrative; why current processes miss entitlements | Finance feedback |
| 3 | The bridge | Upstream / bridge / downstream (section 3) | D1–D5 |
| 4 | The live reveal | One clause, one invoice, one quantified gap, one traceable explanation | |
| 5 | From detection to cash | Detected → Validated → Recovered; built vs target clearly marked | |
| 6 | Proof and the ask | Development-set results with caveats, blind-validation milestone, Finance partner, pilot sponsorship and resources | B-005, partners |

## 8. Relationship to v9
- The v9 freeze still applies to the engine, rules, prompts and data. v10 changes only the app's presentation layer and docs.
- Work is on branch `ai_revenue_leakage_hunter_v5_finance_story`, created from `..._v4_o2c_positioning` so the v4 PR for Mentor 1 stays reviewable. Mentor 1's R1–R5 can be answered on either branch; v10 makes R1, R4 and R5 more visible.
- Checks run 2026-10-26: 100 tests pass; ruff check and format clean; all 6 pages render headlessly (cached AI); "Open evidence" opens F-003.

## 9. Work items
| # | Item | Owner | Status |
|---|---|---|---|
| 27 | Home redesign (KPIs, contract-to-cash strip, priority case, compact queue) | Builder | Done |
| 28 | Detected / Validated / Recovered states; recovery panel as target model | Builder | Done |
| 29 | `docs/live_reveal.md`; problem-first opening in jury storyline | Builder | Done |
| 30 | Finance meeting (section 6) | Builder + P1 | Open |
| 31 | D1–D5 answered by Finance One / AP Suite owner | P2 | Open |
| 32 | Name a Finance champion and a technology / delivery partner | Builder | Open |
| 33 | 6-slide deck | Builder | Open; slides 2, 3 and 6 wait on items 30–32 |
| 34 | Rehearse the live reveal to under 2 minutes, twice, from a clean decision log | Builder | Open |
| 35 | Return to Mentor 2 with what Finance validated, the differentiation evidence and the changed deck and demo | Builder | Open, after 30–34 |

## 10. Next steps (in order)
1. Send the Finance meeting message (section 6).
2. Map Finance One and the AP Suite (D1–D5) before claiming differentiation.
3. Rehearse the live reveal; adjust wording only.
4. Build the deck; mark built vs target on slide 5.
5. Bring the partners into the pitch, only with genuine endorsement.
6. Return to Mentor 2 with evidence (item 35); continue v7/v9 critical path (B-001, B-005 blind holdout).
