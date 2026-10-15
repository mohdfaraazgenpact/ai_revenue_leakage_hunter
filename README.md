# AI Revenue Leakage Hunter — PoC

> Contract says → transactions show → AI finds the gap → $ quantified → evidence shown → human-approved recovery.

**MVP scope:** contracted unit price vs. invoiced unit price, including **missed annual escalations**, **partial escalations**, **amendments not applied** and **prices below contract**.
**Team:** 1 builder + 2 mentors (Business/O2C, AI/Engineering). **Data:** synthetic only. **LLM:** free Google Gemini API.
**Design rule:** the LLM reads contracts and writes explanations; deterministic Python does all the money arithmetic.

The plan is in `../plan_versions/` (v5 is current).

## Quick start (Windows PowerShell)
```powershell
.\scripts\tasks.ps1 setup     # venv, dependencies, pre-commit, creates .env
# edit .env -> GEMINI_API_KEY=<key from https://aistudio.google.com>  (synthetic data only on the free tier)
.\scripts\tasks.ps1 smoke     # one schema-constrained Gemini call
.\scripts\tasks.ps1 all       # generate -> extract (rules + Gemini) -> evaluate -> pipeline -> eval gate -> tests
.\scripts\tasks.ps1 app       # Streamlit demo
.\scripts\tasks.ps1 offline   # demo from cached Gemini responses only (no network)
```
Other tasks: `generate`, `extract`, `run`, `eval`, `test`, `lint`.

## How it works
| Stage | Module | Notes |
|---|---|---|
| Synthetic data factory | `src/generate_synthetic_data.py`, `src/contract_docs.py` | 30 contracts (PDF/DOCX), 8 escalation wordings + CPI, amendments, side letters, traps; 1,578 invoice lines; independent ground truth |
| Document loading | `src/extract/document_loader.py` | Page-tagged text, clause segmentation, verbatim quote verification |
| Extraction (baseline) | `src/extract/rule_extractor.py` | Regex. The honest "rules" comparison |
| Extraction (AI) | `src/extract/llm_extractor.py`, `prompts/extract_terms.v1.md` | Gemini structured output. Quotes verified, values checked against quotes, low confidence goes to `review_queue.csv` |
| LLM access | `src/llm/client.py` | `LLMClient` interface, `GeminiClient` with retry/backoff, disk cache (`data/llm_cache/`), offline mode |
| Price schedule | `src/price_schedule.py` | Effective-dated expected price: amendments, fixed/CPI escalation (floor/cap), approved discounts |
| Reconciliation | `src/reconcile.py` | Net billed (incl. debit/credit notes) vs. expected. Under- and overbilling kept separate |
| Findings | `src/findings.py` | Root-cause classification, owner routing, recoverability ageing, priority |
| Explanations | `src/explain.py`, `prompts/explain_finding.v1.md` | Gemini narrative and rebilling review note. **Numeric guardrail** falls back to a template |
| Orchestration | `src/pipeline.py`, `src/build_all.py` | One call end to end, plus the daily build and eval gate |
| Evaluation | `src/evaluate.py`, `src/evaluate_extraction.py` | Line/contract P/R, $ error, traps, root-cause accuracy; field-level extraction accuracy by wording |
| Demo | `app/streamlit_app.py` | Overview, Findings (price chart, evidence, rebill note, approve/reject), Contract reader, **Jury test**, AI vs rules, Value calculator, Scorecard |

## Current results (synthetic data)
| Terms source | Field accuracy | Leakage lines found | $ found vs seeded | False overbilling | Gate |
|---|---|---|---|---|---|
| Gold terms (engine-only check) | 100% | 100% | $746,690 / $746,690 | $0 | PASS |
| Rules baseline | 94.1% | 77.9% | $549,988 (-26%) | $454,903 | FAIL |
| Gemini | _run with key_ | | | | |

The rules baseline gets 94% of fields right, but it cannot read relative dates ("first anniversary of the Effective Date") or rates in words. Those few misses lose 26% of the money and invent $455k of overbilling.

## Data layout
- Engine inputs: `data/contracts/`, `data/invoice_lines.csv`, `data/billing_adjustments.csv`, `data/customers.csv`, `data/reference/cpi_annual_pct.csv`
- Evaluation only (never used by the detector): `data/eval/` (gold terms, ground truth, expected price schedule, scenarios)
- Outputs: `data/extracted/<rule|llm>/`, `data/output/`, `reports/`

## Limitations
Synthetic demonstration only. It does not prove real-world leakage or recovered revenue. Findings are candidates for human review against the signed contract, invoices, credits and disputes. Do not use client or confidential documents with the free Gemini tier.

## Logs
`docs/decisions.md` (design decisions) and `docs/blockers.md` (open items for mentors).
