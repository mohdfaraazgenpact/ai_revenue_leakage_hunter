# Detection Evaluation - rule

_Generated 2026-10-15 10:50. Terms source: `C:\Users\703227747\.claude\projects\AI Revenue Hunter\ai_revenue_leakage_hunter_poc\data\extracted\rule`. Synthetic data only._

**Gate: FAIL - recall 0.7792 < 0.9; $ error 26.343% > 5.0%; USD 454,903.40 of false overbilling (contract terms misread)**

| Metric | Value | Target |
|---|---|---|
| Line recall | 77.9% | >= 90% |
| Line precision | 100.0% | >= 80% |
| Detected vs seeded $ | 549,988.43 vs 746,689.51 (26.343% error) | within 5% |
| False positives on traps/controls (lines) | 0 | 0 |
| Contract-level recall / precision | 85.7% / 100.0% | - |
| Root-cause accuracy | 94.1% | - |
| Lines routed to review | 0 | - |
| Overbilling detected vs seeded $ | 456552.56 vs 1649.16 | reported separately |

## By seeded scenario

               scenario  lines  seeded_lines  flagged_lines  seeded_usd  detected_usd
  amendment_not_applied    134            30             30   104413.59      99736.83
                control    444             0              0        0.00          0.00
  control_no_escalation    190             0              0        0.00          0.00
      missed_escalation    240           157             97   278456.42     142940.08
            overbilling     72             0              0        0.00          0.00
     partial_escalation    120            52             44    80129.62      58956.39
   price_below_contract    141            69             69   283689.88     248355.13
 trap_approved_discount    141             0              0        0.00          0.00
trap_billing_adjustment     96             0              0        0.00          0.00
