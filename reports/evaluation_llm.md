# Detection Evaluation - llm

_Generated 2026-10-19 13:00. Terms source: `C:\Users\703227747\.claude\projects\AI Revenue Hunter\ai_revenue_leakage_hunter_poc\data\extracted\llm`. Synthetic data only._

**Gate: PASS**

## Underbilling (revenue leakage)

| Metric | Value | Target |
|---|---|---|
| Line recall | 100.0% (311/311) | >= 90% |
| Line precision | 100.0% (311/311) | >= 80% |
| Confusion (n=1580) | TP 311 · FP 0 · FN 0 · TN 1269 | - |
| Detected vs seeded $ | 757,337.56 vs 757,337.56 (0.0% error) | within 5% |
| Line-level abs. $ error (mean / max) | 0.00 / 0.00 (0 lines off by > 1c) | - |
| Flagged leakage lines with the wrong amount | 0 | 0 |
| False positives on traps/controls (lines) | 0 | 0 |
| Contract-level recall / precision | 100.0% / 100.0% | - |
| Root-cause accuracy | 100.0% | - |

## Overbilling (separate problem, never netted)

| Metric | Value |
|---|---|
| Line recall / precision | 100.0% / 100.0% (TP 4 · FP 0 · FN 0) |
| Detected vs seeded $ | 1649.16 vs 1649.16 |
| False overbilling $ | 0.00 |

## Review routing and data integrity

| Metric | Value |
|---|---|
| Outcome accuracy (MATCH / UNDER / OVER / REVIEW) | 100.0% |
| Lines that must go to REVIEW, routed there | 5 / 5 |
| Lines routed to REVIEW (all) | 5 (0 on seeded leakage, counted as missed) |
| REVIEW by issue type | {'CURRENCY_MISMATCH': 1, 'INVALID_INPUT': 2, 'POSSIBLE_DUPLICATE': 2} |
| Exact duplicate rows excluded | 2 |
| Unmatched truth / prediction lines | 0 / 0 |

## By seeded scenario

               scenario  lines  seeded_lines  flagged_lines  review_lines  seeded_usd  detected_usd
  amendment_not_applied    134            30             30             0   104413.59     104413.59
                control    432             0              0             0        0.00          0.00
  control_no_escalation    190             0              0             0        0.00          0.00
      currency_mismatch      1             0              0             1        0.00          0.00
      duplicate_billing      2             0              0             2        0.00          0.00
          invalid_input      2             0              0             2        0.00          0.00
      missed_escalation    240           157            157             0   278456.42     278456.42
            overbilling     72             0              0             0        0.00          0.00
     partial_escalation    120            52             52             0    80129.62      80129.62
   price_below_contract    141            69             69             0   283689.88     283689.88
  return_credit_control      3             0              0             0        0.00          0.00
 trap_approved_discount    141             0              0             0        0.00          0.00
trap_billing_adjustment     96             0              0             0        0.00          0.00
       trap_credit_note      3             0              0             0        0.00          0.00
     unsupported_credit      3             3              3             0    10648.05      10648.05
