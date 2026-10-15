"""Deterministic contract-to-invoice price reconciliation (line level).

    python -m src.reconcile [--terms data/extracted/llm]

Net billed = invoiced line amount + debit notes - credit notes linked to the line.
Underbilling and overbilling are reported separately and never netted against each other.
"""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from src.price_schedule import expected_price, load_cpi, money
from src.schema import ContractTerms

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "output"
TOLERANCE = Decimal("0.01")
REVIEW_THRESHOLD = 0.6  # extraction confidence below this => finding needs term review


def load_terms(terms_dir: Path) -> dict[str, ContractTerms]:
    terms = {}
    for path in sorted(Path(terms_dir).glob("*.json")):
        t = ContractTerms.model_validate_json(path.read_text(encoding="utf-8"))
        terms[t.contract_id] = t
    return terms


def read_inputs(data_dir: Path = DATA):
    invoices = pd.read_csv(data_dir / "invoice_lines.csv", dtype=str)
    adj_path = data_dir / "billing_adjustments.csv"
    adjustments = (
        pd.read_csv(adj_path, dtype=str)
        if adj_path.exists()
        else pd.DataFrame(columns=["invoice_line_id", "adjustment_type", "amount"])
    )
    cpi = load_cpi(data_dir / "reference" / "cpi_annual_pct.csv")
    return invoices, adjustments, cpi


def _adjustment_totals(adjustments: pd.DataFrame) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for r in adjustments.to_dict(orient="records"):
        if not r.get("invoice_line_id"):
            continue
        amt = Decimal(r["amount"])
        sign = 1 if r["adjustment_type"] == "debit_note" else -1
        totals[r["invoice_line_id"]] = totals.get(r["invoice_line_id"], Decimal("0")) + sign * amt
    return totals


def _cite(c):
    return (c.clause_id, c.page, c.quote) if c else (None, None, None)


def reconcile(
    invoices: pd.DataFrame,
    adjustments: pd.DataFrame,
    terms: dict[str, ContractTerms],
    cpi: dict[int, Decimal],
) -> pd.DataFrame:
    adj = _adjustment_totals(adjustments)
    rows = []
    for row in invoices.to_dict(orient="records"):
        out = dict(row)
        t = terms.get(row["contract_id"])
        d = date.fromisoformat(row["invoice_date"])
        if t is None:
            rows.append({**out, "status": "REVIEW", "reason": "No extracted terms for contract"})
            continue
        try:
            px = expected_price(t, row["sku"], d, cpi)
        except (KeyError, ValueError) as exc:
            rows.append({**out, "status": "REVIEW", "reason": str(exc)})
            continue
        qty = Decimal(row["quantity"])
        billed = money(row["invoiced_line_amount"])
        adj_amt = adj.get(row["invoice_line_id"], Decimal("0"))
        net = billed + adj_amt
        expected_amt = money(px.unit_price * qty)
        under = expected_amt - net if expected_amt - net > TOLERANCE else Decimal("0")
        over = net - expected_amt if net - expected_amt > TOLERANCE else Decimal("0")
        status = "POTENTIAL_UNDERBILLING" if under else "POTENTIAL_OVERBILLING" if over else "MATCH"
        conf = min(t.field_confidence.values()) if t.field_confidence else 1.0
        pc, pp, pq = _cite(px.citations.get("price"))
        ec, ep, eq = _cite(px.citations.get("escalation"))
        ac, ap, aq = _cite(px.citations.get("amendment"))
        dc, dp, dq = _cite(px.citations.get("discount"))
        rows.append(
            {
                **out,
                "expected_unit_price": f"{px.unit_price:.2f}",
                "expected_line_amount": f"{expected_amt:.2f}",
                "adjustments_amount": f"{adj_amt:.2f}",
                "net_billed_amount": f"{net:.2f}",
                "potential_underbilling": f"{under:.2f}",
                "potential_overbilling": f"{over:.2f}",
                "status": status,
                "reason": {
                    "MATCH": "Net billed amount matches the contract-derived amount.",
                    "POTENTIAL_UNDERBILLING": "Net billed amount is below the contract-derived amount.",
                    "POTENTIAL_OVERBILLING": "Net billed amount is above the contract-derived amount.",
                }[status],
                "anchor_source": px.anchor_source,
                "anchor_price": f"{px.anchor_price:.2f}",
                "n_escalations": len(px.escalations),
                "discount_pct": "" if px.discount_pct is None else str(px.discount_pct),
                "calculation": px.formula(),
                "price_clause_id": pc,
                "price_page": pp,
                "price_quote": pq,
                "escalation_clause_id": ec,
                "escalation_page": ep,
                "escalation_quote": eq,
                "amendment_clause_id": ac,
                "amendment_page": ap,
                "amendment_quote": aq,
                "discount_clause_id": dc,
                "discount_page": dp,
                "discount_quote": dq,
                "terms_source": t.source,
                "extraction_confidence": round(conf, 3),
                "needs_term_review": conf < REVIEW_THRESHOLD,
            }
        )
    return pd.DataFrame(rows)


def run(terms_dir: Path, data_dir: Path = DATA, out_dir: Path = OUTPUT) -> pd.DataFrame:
    invoices, adjustments, cpi = read_inputs(data_dir)
    result = reconcile(invoices, adjustments, load_terms(terms_dir), cpi)
    out_dir.mkdir(parents=True, exist_ok=True)
    result.to_csv(out_dir / "line_results.csv", index=False)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--terms",
        default=str(DATA / "eval" / "gold"),
        help="Directory of ContractTerms JSON (gold, data/extracted/rule, data/extracted/llm)",
    )
    args = ap.parse_args()
    result = run(Path(args.terms))
    under = (
        result.get("potential_underbilling", pd.Series(dtype=str)).fillna("0").map(Decimal).sum()
    )
    print(f"Reconciled {len(result)} lines using terms from {args.terms}")
    print(result["status"].value_counts().to_string())
    print(f"Potential underbilling: USD {under:,.2f} (synthetic data; not validated recovery)")


if __name__ == "__main__":
    main()
