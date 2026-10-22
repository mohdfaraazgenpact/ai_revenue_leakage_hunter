# Detection Evaluation - rule

_Generated 2026-10-19 13:00. Terms source: `C:\Users\703227747\.claude\projects\AI Revenue Hunter\ai_revenue_leakage_hunter_poc\data\extracted\rule`. Synthetic data only._

**Gate: FAIL - recall 0.7138 < 0.9; $ error 34.057% > 5.0%; USD 139,908.50 of false overbilling (contract terms misread)**

## Underbilling (revenue leakage)

| Metric | Value | Target |
|---|---|---|
| Line recall | 71.4% (222/311) | >= 90% |
| Line precision | 100.0% (222/222) | >= 80% |
| Confusion (n=1580) | TP 222 · FP 0 · FN 89 · TN 1269 | - |
| Detected vs seeded $ | 499,409.14 vs 757,337.56 (34.057% error) | within 5% |
| Line-level abs. $ error (mean / max) | 163.25 / 5656.92 (95 lines off by > 1c) | - |
| Flagged leakage lines with the wrong amount | 6 | 0 |
| False positives on traps/controls (lines) | 0 | 0 |
| Contract-level recall / precision | 81.2% / 100.0% | - |
| Root-cause accuracy | 93.8% | - |

## Overbilling (separate problem, never netted)

| Metric | Value |
|---|---|
| Line recall / precision | 100.0% / 4.3% (TP 4 · FP 89 · FN 0) |
| Detected vs seeded $ | 141557.66 vs 1649.16 |
| False overbilling $ | 139908.50 |

## Review routing and data integrity

| Metric | Value |
|---|---|
| Outcome accuracy (MATCH / UNDER / OVER / REVIEW) | 73.5% |
| Lines that must go to REVIEW, routed there | 5 / 5 |
| Lines routed to REVIEW (all) | 335 (89 on seeded leakage, counted as missed) |
| REVIEW by issue type | {'CURRENCY_MISMATCH': 1, 'INVALID_INPUT': 2, 'POSSIBLE_DUPLICATE': 2, 'TERMS_NOT_DETERMINABLE': 330} |
| Exact duplicate rows excluded | 2 |
| Unmatched truth / prediction lines | 0 / 0 |

## By seeded scenario

               scenario  lines  seeded_lines  flagged_lines  review_lines  seeded_usd  detected_usd
  amendment_not_applied    134            30             30             0   104413.59      99736.83
                control    432             0              0           210        0.00          0.00
  control_no_escalation    190             0              0             0        0.00          0.00
      currency_mismatch      1             0              0             1        0.00          0.00
      duplicate_billing      2             0              0             2        0.00          0.00
          invalid_input      2             0              0             2        0.00          0.00
      missed_escalation    240           157             97            72   278456.42     142940.08
            overbilling     72             0              0             0        0.00          0.00
     partial_escalation    120            52             44            24    80129.62      58956.39
   price_below_contract    141            69             48            21   283689.88     187127.79
  return_credit_control      3             0              0             1        0.00          0.00
 trap_approved_discount    141             0              0             0        0.00          0.00
trap_billing_adjustment     96             0              0             0        0.00          0.00
       trap_credit_note      3             0              0             2        0.00          0.00
     unsupported_credit      3             3              3             0    10648.05      10648.05
