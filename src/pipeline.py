"""End-to-end run: terms -> reconciliation -> findings -> explanations.

python -m src.pipeline                          # detector run: terms from EXTRACTOR (llm, else rule)
python -m src.pipeline --explain                # add Gemini narratives (cached)
python -m src.pipeline --oracle                 # ENGINE-ONLY evaluation with the answer-key terms

A detector run never falls back to the answer key (data/eval/gold). If no extracted terms exist it
fails with a clear message. Oracle runs are labelled as such in summary.json and the app.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from src.explain import explain_findings
from src.findings import RECOVERABILITY_BASIS, build_findings, findings_frame
from src.reconcile import (
    DATA,
    OUTPUT,
    load_terms,
    parse_decimal,
    read_inputs,
    reconcile_with_issues,
)

GOLD_DIR = DATA / "eval" / "gold"
ORACLE_LABEL = "ORACLE - answer-key terms, engine-only evaluation (not a detector run)"


class MissingExtractedTerms(FileNotFoundError):
    pass


def default_terms_dir() -> Path:
    """Extracted terms for a detector run. Never the answer key."""
    from dotenv import load_dotenv

    load_dotenv(DATA.parent / ".env")
    pref = os.getenv("EXTRACTOR", "llm")
    for name in dict.fromkeys((pref, "llm", "rule")):
        d = DATA / "extracted" / name
        if d.exists() and any(d.glob("*.json")):
            return d
    raise MissingExtractedTerms(
        "No extracted contract terms found in data/extracted/<llm|rule>/. Run "
        "`python -m src.extract.run_extraction --extractor rule` (or llm) first. "
        "For an engine-only check against the answer key use `python -m src.pipeline --oracle`."
    )


def is_oracle(terms_dir: Path | None) -> bool:
    if terms_dir is None:
        return False
    p = Path(terms_dir).resolve()
    return p == GOLD_DIR.resolve() or (DATA / "eval").resolve() in p.parents


def run(
    terms_dir: Path | None = None,
    data_dir: Path = DATA,
    out_dir: Path = OUTPUT,
    explain: bool = False,
    llm=None,
    terms: dict | None = None,
) -> dict:
    t0 = time.perf_counter()
    if terms is None:
        terms_dir = Path(terms_dir) if terms_dir else default_terms_dir()
        terms = load_terms(terms_dir)
    invoices, adjustments, cpi = read_inputs(data_dir)
    customers = dict(
        pd.read_csv(data_dir / "customers.csv", dtype=str)[
            ["customer_id", "customer_name"]
        ].itertuples(index=False, name=None)
    )
    lines, issues = reconcile_with_issues(invoices, adjustments, terms, cpi)
    reconciled_dates = lines.loc[lines["issue_type"].eq(""), "invoice_date"] if len(lines) else []
    as_of = date.fromisoformat(max(reconciled_dates)) if len(reconciled_dates) else None
    findings = build_findings(lines, terms, cpi, customers, as_of=as_of)
    explain_findings(findings, terms, llm=llm, use_llm=explain or llm is not None)
    out_dir.mkdir(parents=True, exist_ok=True)
    lines.to_csv(out_dir / "line_results.csv", index=False)
    issues.to_csv(out_dir / "input_issues.csv", index=False)
    findings_frame(findings).to_csv(out_dir / "findings.csv", index=False)
    (out_dir / "findings.json").write_text(
        json.dumps([asdict(f) for f in findings], indent=2, default=str), encoding="utf-8"
    )
    under = [f for f in findings if f.root_cause != "OVERBILLING"]
    counted = lines[~lines["status"].isin(["DUPLICATE"]) & lines["issue_type"].ne("INVALID_INPUT")]
    billed = sum(
        (parse_decimal(x) or Decimal("0") for x in counted["invoiced_line_amount"]), Decimal("0")
    )
    summary = {
        "run_mode": ORACLE_LABEL
        if is_oracle(terms_dir) or any(t.source == "gold" for t in terms.values())
        else "detector",
        "terms_source": str(terms_dir) if terms_dir else "in-memory terms",
        "contracts": len(terms),
        "invoice_lines": len(lines),
        "billed_total": str(billed),
        "findings": len(under),
        "potential_underbilling": str(sum((f.amount for f in under), Decimal("0"))),
        "recoverable_estimate": str(sum((f.recoverable_estimate for f in under), Decimal("0"))),
        "recoverability_basis": RECOVERABILITY_BASIS.format(as_of=as_of or "the latest invoice"),
        "overbilling_findings": len(findings) - len(under),
        "potential_overbilling": str(
            sum((f.amount for f in findings if f.root_cause == "OVERBILLING"), Decimal("0"))
        ),
        "lines_needing_review": int((lines["status"] == "REVIEW").sum()),
        "duplicate_rows_excluded": int((lines["status"] == "DUPLICATE").sum()),
        "lines_by_status": lines["status"].value_counts().sort_index().to_dict(),
        "review_by_issue": lines.loc[lines["issue_type"].ne(""), "issue_type"]
        .value_counts()
        .sort_index()
        .to_dict(),
        "input_issues": len(issues),
        "runtime_seconds": round(time.perf_counter() - t0, 2),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return {"summary": summary, "lines": lines, "findings": findings, "issues": issues}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--terms", default=None, help="Directory of extracted ContractTerms JSON")
    ap.add_argument(
        "--oracle",
        action="store_true",
        help="Use the answer-key terms (data/eval/gold) for an engine-only evaluation run",
    )
    ap.add_argument("--explain", action="store_true")
    a = ap.parse_args()
    terms_dir = GOLD_DIR if a.oracle else Path(a.terms) if a.terms else None
    try:
        res = run(terms_dir, explain=a.explain)
    except MissingExtractedTerms as exc:
        raise SystemExit(f"ERROR: {exc}") from None
    print(json.dumps(res["summary"], indent=2))
    print(
        findings_frame(res["findings"])[
            [
                "finding_id",
                "contract_id",
                "sku",
                "root_cause",
                "line_count",
                "amount",
                "priority_score",
                "owner",
            ]
        ]
        .head(15)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
