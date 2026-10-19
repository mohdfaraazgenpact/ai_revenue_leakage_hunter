# AI Revenue Leakage Hunter — PoC

> Contract says → transactions show → AI finds the gap → $ quantified → evidence shown → human review.

**MVP scope:** contracted unit price vs. invoiced unit price, including **missed annual escalations**, **partial escalations**, **amendments not applied**, **prices below contract** and **unsupported credit notes**.
**Team:** 1 builder + 2 mentors (Business/O2C, AI/Engineering). **Data:** synthetic only. **LLM:** Claude (`claude-sonnet-5-5`) through Claude Code headless mode (`claude -p`) on the signed-in licence; the free Gemini API remains a switchable option (`LLM_PROVIDER`).
**Design rule:** the LLM reads contracts and writes explanations; deterministic Python does all the money arithmetic.

The plan is in `../plan_versions/` (v6 is current). The jury storyline is in [`docs/jury_storyline.md`](docs/jury_storyline.md) and the release gates in [`docs/release_gates.md`](docs/release_gates.md).

## Quick start (Windows PowerShell)
```powershell
.\scripts\tasks.ps1 setup     # venv, dependencies, pre-commit, creates .env
# .env -> LLM_PROVIDER=claude_code (Claude Code must be installed and signed in; no API key)
#        or LLM_PROVIDER=gemini + GEMINI_API_KEY=<key>.  Synthetic data only with either provider.
.\scripts\tasks.ps1 smoke     # one schema-constrained call to the configured LLM
.\scripts\tasks.ps1 all       # generate -> extract (rules + AI) -> evaluate -> pipeline -> eval gate -> README results -> tests
.\scripts\tasks.ps1 app       # Streamlit demo
.\scripts\tasks.ps1 offline   # demo from cached AI responses only (no network)
python -m vetting.run_vetting # 43-case vetting checklist -> vetting/results.json
```
Other tasks: `generate`, `extract`, `run`, `eval`, `test`, `lint`.

If `pip install` fails with *WinError 206 (path too long)*, move the project to a shorter path (for example `C:\dev\`) or enable Windows long paths.

## How it works
| Stage | Module | Notes |
|---|---|---|
| Synthetic data factory | `src/generate_synthetic_data.py`, `src/contract_docs.py` | 30 contracts (PDF/DOCX), 8 escalation wordings + CPI, amendments, side letters, traps; invoice lines and independent ground truth. An integrity overlay adds credit notes, returns, duplicates, a currency mismatch and malformed rows |
| Document loading | `src/extract/document_loader.py` | Page-tagged text, clause segmentation, verbatim quote verification |
| Extraction (baseline) | `src/extract/rule_extractor.py` | Regex. The honest "rules" comparison. Lowers its confidence when it cannot resolve an escalation date |
| Extraction (AI) | `src/extract/llm_extractor.py`, `prompts/extract_terms.v2.md` | Schema-constrained JSON from the configured LLM. Quotes verified, values checked against quotes, low confidence goes to `review_queue.csv`. The prompt treats the contract as untrusted data |
| LLM access | `src/llm/client.py` | `LLMClient` interface. `ClaudeCodeClient` runs `claude -p` as a single stateless turn with all tools disabled, `--safe-mode`, no saved session and an empty temp working directory, so the model sees only the prompt; output is validated against the Pydantic schema (`--json-schema`). `GeminiClient` as an alternative. Retry/backoff, disk cache (`data/llm_cache/`) recording provider and models used, offline mode. `provenance.txt` in each extraction folder records reader, model and prompt version |
| Price schedule | `src/price_schedule.py` | Effective-dated expected price: amendments, fixed/CPI escalation (floor/cap), compounding **or simple** escalation, approved discounts. Unresolved terms raise instead of being ignored |
| Reconciliation | `src/reconcile.py` | Row validation, duplicates, currency and invoice-arithmetic checks, debit/credit/return adjustments, then net billed vs. expected. Under- and overbilling kept separate |
| Findings | `src/findings.py` | Root-cause classification, owner routing, illustrative recoverability, priority |
| Explanations | `src/explain.py`, `prompts/explain_finding.v1.md` | LLM narrative and rebilling review note. **Numeric guardrail** falls back to a template |
| Orchestration | `src/pipeline.py`, `src/build_all.py` | One call end to end, plus the daily build, eval gate and README results |
| Evaluation | `src/evaluate.py`, `src/evaluate_extraction.py`, `src/results_report.py` | Underbilling and overbilling metrics kept separate, line-level $ error, review routing, ambiguous/unmatched-key checks; field-level extraction accuracy by wording |
| Demo | `app/streamlit_app.py` | Overview, Findings (price chart, evidence, rebill note, approve/reject, CSV exports, review queue), Contract reader, Jury test, AI vs rules, Value calculator (simulated), Scorecard |

## Data integrity rules
The engine never guesses and never drops a record silently. A line it cannot price safely goes to **REVIEW** with an issue type. It is listed in `data/output/input_issues.csv` with its source file and row, and it is never counted as a match or as leakage.

| Issue type | When |
|---|---|
| `INVALID_INPUT` | Date not `YYYY-MM-DD`, non-numeric or negative quantity/price/amount, missing currency or IDs |
| `EXACT_DUPLICATE` (status `DUPLICATE`) | Identical copy of an earlier row: kept once, excluded from totals |
| `DUPLICATE_ID_CONFLICT` | Same `invoice_line_id`, different content |
| `POSSIBLE_DUPLICATE` | Same invoice, SKU, date, quantity and amount under a new line ID |
| `CURRENCY_MISMATCH` | Invoice currency differs from contract currency (no FX policy yet) |
| `ARITHMETIC_MISMATCH` | quantity × unit price differs from the line amount by more than $0.01 |
| `ADJUSTMENT_ISSUE` | Adjustment type other than `debit_note` / `credit_note` / `return_credit`, non-positive amount, or a return without a quantity |
| `TERMS_MISSING` / `TERMS_NOT_DETERMINABLE` | No terms for the contract, SKU not priced, date outside the term, or an escalation clause with an unresolved date or rate |

**Oracle mode.** `data/eval/gold` holds the answer-key terms. A detector run never falls back to it. Use `python -m src.pipeline --oracle` only to check the reconciliation engine in isolation. Those runs are labelled `ORACLE` in `summary.json`, and the app shows a warning banner.

## Current results (synthetic data)
<!-- results:start -->
_Generated by `python -m src.results_report` at the end of `src.build_all`. Do not edit by hand._

Dataset fingerprint `cca8a43cec67` (generator seed 42) · code `e98f45a + uncommitted changes` · generated 2026-10-19 12:02 · 1580 ground-truth invoice lines.

| Terms source | Field accuracy | Leakage lines found | Precision | $ found vs seeded | False overbilling | Lines to review | Gate |
|---|---|---|---|---|---|---|---|
| Answer key (engine-only check, not a detector run) | 100% (by definition) | 100.0% (311/311) | 100.0% | $757,338 / $757,338 (0.0% error) | $0 | 5 | PASS |
| Rules baseline (regex) | 94.1% | 71.4% (222/311) | 100.0% | $499,409 / $757,338 (34.057% error) | $139,908 | 335 | FAIL |
| AI extraction: offline (claude-sonnet-5-5), prompt extract_terms.v2 | 100.0% | 100.0% (311/311) | 100.0% | $757,338 / $757,338 (0.0% error) | $0 | 5 | PASS |

Definitions: *Leakage lines found* = line recall on seeded underbilling; *Precision* = share of flagged underbilling lines that are seeded leakage; *$ found vs seeded* = aggregate underbilling detected vs seeded; *False overbilling* = overbilling $ on lines with no seeded overbilling; *Lines to review* = lines the engine refused to price (invalid input, duplicates, currency, arithmetic, adjustments or undeterminable terms), counted as missed when they hold leakage. Full definitions and per-scenario tables: `reports/evaluation_<source>.md`.
<!-- results:end -->

**What this does and does not show.** The answer-key row proves the money engine is exact when the terms are right. The rules row shows what a non-AI extractor achieves on the same documents. Rules miss relative dates and rates written in words; those contracts now go to review instead of being mispriced, and three misread rates still produce false overbilling. The AI row is Claude (`claude-sonnet-5-5` via Claude Code) reading the same 30 documents with prompt v2: every key field correct, all 106 quotes verified verbatim, and engine results identical to the answer key. **These are development-set results:** there is no blind holdout yet (B-005), so every number comes from the same generator that produced the rules' test documents, whose wording is cleaner and more regular than real contracts. Do not quote the AI figures as validated accuracy until the blind set has been run against thresholds agreed in advance. Live Claude calls are not bit-for-bit repeatable (no temperature setting in the CLI); `data/llm_cache/` makes this run replayable offline (`tasks.ps1 offline`).

## Data layout
- Engine inputs: `data/contracts/`, `data/invoice_lines.csv`, `data/billing_adjustments.csv`, `data/customers.csv`, `data/reference/cpi_annual_pct.csv`
- Evaluation only (never used by the detector): `data/eval/` (gold terms, ground truth with `expected_outcome`, expected price schedule, scenarios)
- Outputs: `data/extracted/<rule|llm>/`, `data/output/` (`line_results.csv`, `findings.csv`, `input_issues.csv`, `summary.json`), `reports/`

## Limitations
Synthetic demonstration only. It does not prove real-world leakage or recovered revenue. Findings are candidates for human review against the signed contract, invoices, credits and disputes. Recoverability is an illustrative age-weighted estimate, not validated against claim periods. The value calculator is a simulation. Do not use client or confidential documents with the free Gemini tier.

## Logs
`docs/decisions.md` (design decisions), `docs/blockers.md` (open items for mentors), `docs/release_gates.md` (gate status), `vetting/results.json` (checklist results).
