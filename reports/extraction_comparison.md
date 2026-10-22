# Extraction Accuracy vs Gold (2026-10-19 13:00)

_Synthetic contracts only._

| Extractor | Key-field accuracy | Contracts fully correct | Citations verified | Spurious items |
|---|---|---|---|---|
| llm | 100.0% | 30/30 | 100% | 0 |
| rule | 94.1% | 21/30 | - | 0 |

## Escalation clause correct, by wording variant

| Variant | llm | rule |
|---|---|---|
| cpi/v0 | 2/2 | 0/2 |
| cpi/v1 | 2/2 | 2/2 |
| fixed_pct/v1 | 3/3 | 3/3 |
| fixed_pct/v2 | 3/3 | 3/3 |
| fixed_pct/v3 | 4/4 | 0/4 |
| fixed_pct/v4 | 3/3 | 0/3 |
| fixed_pct/v5 | 3/3 | 3/3 |
| fixed_pct/v6 | 4/4 | 4/4 |
| fixed_pct/v7 | 2/2 | 2/2 |
| fixed_pct/v8 | 1/1 | 1/1 |
| none/v0 | 1/1 | 1/1 |
| none/v1 | 2/2 | 2/2 |

## Accuracy by field group

| Group | llm | rule |
|---|---|---|
| amendments | 100% | 100% |
| customer_and_dates | 100% | 100% |
| discounts | 100% | 100% |
| escalation | 100% | 83% |
| prices | 100% | 100% |
