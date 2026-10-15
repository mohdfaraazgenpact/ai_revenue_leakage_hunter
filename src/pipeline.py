"""End-to-end run: terms -> reconciliation -> findings -> explanations.

python -m src.pipeline                          # terms from EXTRACTOR (default: data/extracted/llm if present)
python -m src.pipeline --terms data/eval/gold   # oracle terms (engine-only accuracy)
python -m src.pipeline --explain                # add Gemini narratives (cached)
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

import pandas as pd

from src.explain import explain_findings
from src.findings import build_findings, findings_frame
from src.reconcile import DATA, OUTPUT, load_terms, read_inputs, reconcile


def default_terms_dir() -> Path:
    from dotenv import load_dotenv

    load_dotenv(DATA.parent / ".env")
    pref = os.getenv("EXTRACTOR", "llm")
    for name in (pref, "llm", "rule"):
        d = DATA / "extracted" / name
        if d.exists() and any(d.glob("*.json")):
            return d
    return DATA / "eval" / "gold"


def run(
    terms_dir: Path | None = None,
    data_dir: Path = DATA,
    out_dir: Path = OUTPUT,
    explain: bool = False,
    llm=None,
    terms: dict | None = None,
) -> dict:
    t0 = time.perf_counter()
    terms_dir = Path(terms_dir) if terms_dir else default_terms_dir()
    terms = terms if terms is not None else load_terms(terms_dir)
    invoices, adjustments, cpi = read_inputs(data_dir)
    customers = dict(
        pd.read_csv(data_dir / "customers.csv", dtype=str)[
            ["customer_id", "customer_name"]
        ].itertuples(index=False, name=None)
    )
    lines = reconcile(invoices, adjustments, terms, cpi)
    findings = build_findings(lines, terms, cpi, customers)
    explain_findings(findings, terms, llm=llm, use_llm=explain or llm is not None)
    out_dir.mkdir(parents=True, exist_ok=True)
    lines.to_csv(out_dir / "line_results.csv", index=False)
    findings_frame(findings).to_csv(out_dir / "findings.csv", index=False)
    (out_dir / "findings.json").write_text(
        json.dumps([asdict(f) for f in findings], indent=2, default=str), encoding="utf-8"
    )
    under = [f for f in findings if f.root_cause != "OVERBILLING"]
    summary = {
        "terms_source": str(terms_dir),
        "contracts": len(terms),
        "invoice_lines": len(lines),
        "billed_total": str(sum(Decimal(x) for x in invoices["invoiced_line_amount"])),
        "findings": len(under),
        "potential_underbilling": str(sum((f.amount for f in under), Decimal("0"))),
        "recoverable_estimate": str(sum((f.recoverable_estimate for f in under), Decimal("0"))),
        "overbilling_findings": len(findings) - len(under),
        "lines_needing_review": int((lines["status"] == "REVIEW").sum()),
        "runtime_seconds": round(time.perf_counter() - t0, 2),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return {"summary": summary, "lines": lines, "findings": findings}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--terms", default=None)
    ap.add_argument("--explain", action="store_true")
    a = ap.parse_args()
    res = run(Path(a.terms) if a.terms else None, explain=a.explain)
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
