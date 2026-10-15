"""Deterministic contract-to-invoice price reconciliation (line level).

    python -m src.reconcile --terms data/extracted/llm

Net billed = invoiced line amount + debit notes - credit notes - return credits linked to the line.
Underbilling and overbilling are reported separately and never netted against each other.

Data integrity (every problem is quarantined per row and logged; one bad row never aborts a run):
- Rows are validated before any arithmetic: ISO dates (YYYY-MM-DD) only, numeric quantity / unit
  price / line amount, no negative quantities or prices (returns are booked as ``return_credit``
  adjustments), a 3-letter currency and non-blank identifiers. Failures -> REVIEW / INVALID_INPUT.
- Exact duplicate rows (same ID, same content) are kept once; the copies get status DUPLICATE and
  are excluded from every total. Rows that share an ID with different content -> REVIEW.
- A second line with the same invoice, SKU, date, quantity, price and amount under a new ID ->
  REVIEW / POSSIBLE_DUPLICATE (never deleted, never counted twice).
- Invoice currency must equal the contract currency (no FX conversion policy yet) -> else REVIEW.
- quantity x unit price must equal the line amount within TOLERANCE -> else REVIEW.
- Only debit_note (+), credit_note (-) and return_credit (-, with a returned quantity) adjustments
  are accepted, with positive amounts. Anything else puts the line in REVIEW.
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from src.price_schedule import expected_price, load_cpi, money
from src.schema import ContractTerms

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = DATA / "output"
TOLERANCE = Decimal("0.01")
REVIEW_THRESHOLD = 0.6  # extraction confidence below this => finding needs term review

INVOICE_FILE, ADJUSTMENT_FILE = "invoice_lines.csv", "billing_adjustments.csv"
REQUIRED_TEXT = ("invoice_line_id", "invoice_id", "contract_id", "sku")
ADJUSTMENT_SIGN = {"debit_note": 1, "credit_note": -1, "return_credit": -1}
ISSUE_COLUMNS = ["source_file", "source_row", "record_id", "issue_type", "detail"]
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CURRENCY = re.compile(r"^[A-Z]{3}$")


def load_terms(terms_dir: Path) -> dict[str, ContractTerms]:
    terms = {}
    for path in sorted(Path(terms_dir).glob("*.json")):
        t = ContractTerms.model_validate_json(path.read_text(encoding="utf-8"))
        terms[t.contract_id] = t
    return terms


def read_inputs(data_dir: Path = DATA):
    invoices = pd.read_csv(data_dir / INVOICE_FILE, dtype=str, keep_default_na=False)
    adj_path = data_dir / ADJUSTMENT_FILE
    adjustments = (
        pd.read_csv(adj_path, dtype=str, keep_default_na=False)
        if adj_path.exists()
        else pd.DataFrame(columns=["invoice_line_id", "adjustment_type", "amount"])
    )
    cpi = load_cpi(data_dir / "reference" / "cpi_annual_pct.csv")
    return invoices, adjustments, cpi


# ---------------------------------------------------------------- validation helpers
def _text(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip()


def parse_decimal(v) -> Decimal | None:
    s = _text(v).replace(",", "")
    if not s:
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def parse_iso_date(v) -> date | None:
    s = _text(v)
    if not ISO_DATE.match(s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def validate_line(row: dict) -> tuple[dict, list[str]]:
    """Parsed values and a list of problems (empty when the row is usable)."""
    problems = [f"{c} is blank" for c in REQUIRED_TEXT if not _text(row.get(c))]
    d = parse_iso_date(row.get("invoice_date"))
    if d is None:
        problems.append(f"invoice_date '{_text(row.get('invoice_date'))}' is not YYYY-MM-DD")
    vals = {"date": d}
    for key, col in (
        ("qty", "quantity"),
        ("unit", "invoiced_unit_price"),
        ("amount", "invoiced_line_amount"),
    ):
        x = parse_decimal(row.get(col))
        if x is None:
            problems.append(f"{col} '{_text(row.get(col))}' is not a number")
        elif x < 0:
            problems.append(f"{col} {x} is negative (book returns/credits as adjustments)")
        vals[key] = x
    cur = _text(row.get("currency")).upper()
    if not CURRENCY.match(cur):
        problems.append(f"currency '{_text(row.get('currency'))}' is not a 3-letter code")
    vals["currency"] = cur
    return vals, problems


def _adjustments(adjustments: pd.DataFrame, line_ids: set[str]):
    """Signed totals and returned quantities per line, lines with bad adjustments, issue log."""
    totals: dict[str, Decimal] = {}
    returned: dict[str, Decimal] = {}
    bad: dict[str, list[str]] = {}
    issues: list[dict] = []
    for i, r in enumerate(adjustments.to_dict(orient="records"), start=2):
        lid, aid = _text(r.get("invoice_line_id")), _text(r.get("adjustment_id")) or f"row {i}"
        kind = _text(r.get("adjustment_type")).lower()
        amt = parse_decimal(r.get("amount"))
        problem = None
        if not lid:
            problem = "adjustment is not linked to an invoice line"
        elif lid not in line_ids:
            problem = f"adjustment references unknown invoice line {lid}"
        elif kind not in ADJUSTMENT_SIGN:
            problem = f"unsupported adjustment_type '{kind}'"
        elif amt is None or amt <= 0:
            problem = f"amount '{_text(r.get('amount'))}' must be a positive number"
        elif kind == "return_credit":
            q = parse_decimal(r.get("quantity"))
            if q is None or q <= 0:
                problem = "return_credit needs a positive returned quantity"
            else:
                returned[lid] = returned.get(lid, Decimal("0")) + q
        if problem:
            issues.append(
                {
                    "source_file": ADJUSTMENT_FILE,
                    "source_row": i,
                    "record_id": aid,
                    "issue_type": "ADJUSTMENT_ISSUE",
                    "detail": problem,
                }
            )
            if lid in line_ids:
                bad.setdefault(lid, []).append(f"{aid}: {problem}")
            continue
        totals[lid] = totals.get(lid, Decimal("0")) + ADJUSTMENT_SIGN[kind] * amt
    return totals, returned, bad, issues


def _duplicate_status(invoices: pd.DataFrame) -> dict[int, tuple[str, str]]:
    """Row index -> (status/issue, reason) for duplicate IDs and duplicate business keys."""
    out: dict[int, tuple[str, str]] = {}
    ids = invoices["invoice_line_id"].map(_text)
    content = invoices.astype(str).apply(lambda s: s.str.strip())
    for lid, idx in ids.groupby(ids).groups.items():
        if not lid or len(idx) < 2:
            continue
        rows = content.loc[idx]
        if len(rows.drop_duplicates()) == 1:
            for k in list(idx)[1:]:
                out[k] = ("EXACT_DUPLICATE", f"Exact copy of source row {idx[0] + 2}")
        else:
            for k in idx:
                out[k] = (
                    "DUPLICATE_ID_CONFLICT",
                    f"invoice_line_id {lid} is used by {len(idx)} rows with different content",
                )
    key_cols = [
        "invoice_id",
        "sku",
        "invoice_date",
        "quantity",
        "invoiced_unit_price",
        "invoiced_line_amount",
    ]
    seen: dict[tuple, str] = {}
    for k, r in content.iterrows():
        if k in out:
            continue
        key = tuple(r.get(c, "") for c in key_cols)
        if key in seen and seen[key] != r["invoice_line_id"]:
            out[k] = (
                "POSSIBLE_DUPLICATE",
                f"Same invoice, SKU, date, quantity and amount as {seen[key]}",
            )
        else:
            seen.setdefault(key, r["invoice_line_id"])
    return out


def _cite(c):
    return (c.clause_id, c.page, c.quote) if c else (None, None, None)


# ---------------------------------------------------------------- reconciliation
def reconcile_with_issues(
    invoices: pd.DataFrame,
    adjustments: pd.DataFrame,
    terms: dict[str, ContractTerms],
    cpi: dict[int, Decimal],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    invoices = invoices.reset_index(drop=True).fillna("")
    adj, returned, bad_adj, issues = _adjustments(
        adjustments.fillna(""), set(invoices["invoice_line_id"].map(_text))
    )
    dups = _duplicate_status(invoices)
    rows: list[dict] = []

    def hold(out: dict, issue: str, reason: str, status: str = "REVIEW"):
        rows.append({**out, "status": status, "issue_type": issue, "reason": reason})
        issues.append(
            {
                "source_file": INVOICE_FILE,
                "source_row": out["source_row"],
                "record_id": _text(out.get("invoice_line_id")),
                "issue_type": issue,
                "detail": reason,
            }
        )

    for k, row in enumerate(invoices.to_dict(orient="records")):
        out = {**row, "source_row": k + 2}
        vals, problems = validate_line(row)
        if problems:
            hold(out, "INVALID_INPUT", "; ".join(problems))
            continue
        if k in dups:
            issue, reason = dups[k]
            hold(out, issue, reason, "DUPLICATE" if issue == "EXACT_DUPLICATE" else "REVIEW")
            continue
        t = terms.get(_text(row["contract_id"]))
        if t is None:
            hold(out, "TERMS_MISSING", "No extracted terms for contract")
            continue
        if vals["currency"] != t.currency.upper():
            hold(
                out,
                "CURRENCY_MISMATCH",
                f"Invoice currency {vals['currency']} differs from contract currency {t.currency}; "
                "no FX conversion policy is configured",
            )
            continue
        qty, billed = vals["qty"], money(vals["amount"])
        arithmetic = money(qty * vals["unit"])
        if abs(arithmetic - billed) > TOLERANCE:
            hold(
                out,
                "ARITHMETIC_MISMATCH",
                f"quantity {qty} x unit price {vals['unit']} = {arithmetic:.2f} but line amount is "
                f"{billed:.2f}",
            )
            continue
        lid = _text(row["invoice_line_id"])
        if lid in bad_adj:
            hold(out, "ADJUSTMENT_ISSUE", "; ".join(bad_adj[lid]))
            continue
        ret_qty = returned.get(lid, Decimal("0"))
        if ret_qty > qty:
            hold(
                out,
                "ADJUSTMENT_ISSUE",
                f"returned quantity {ret_qty} exceeds invoiced quantity {qty}",
            )
            continue
        try:
            px = expected_price(t, row["sku"], vals["date"], cpi)
        except (KeyError, ValueError) as exc:
            hold(out, "TERMS_NOT_DETERMINABLE", str(exc).strip("'\""))
            continue
        adj_amt = adj.get(lid, Decimal("0"))
        net = billed + adj_amt
        expected_amt = money(px.unit_price * (qty - ret_qty))
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
                "returned_quantity": str(ret_qty) if ret_qty else "",
                "adjustments_amount": f"{adj_amt:.2f}",
                "net_billed_amount": f"{net:.2f}",
                "potential_underbilling": f"{under:.2f}",
                "potential_overbilling": f"{over:.2f}",
                "status": status,
                "issue_type": "",
                "reason": {
                    "MATCH": "Net billed amount matches the contract-derived amount.",
                    "POTENTIAL_UNDERBILLING": "Net billed amount is below the contract-derived amount.",
                    "POTENTIAL_OVERBILLING": "Net billed amount is above the contract-derived amount.",
                }[status],
                "anchor_source": px.anchor_source,
                "anchor_price": f"{px.anchor_price:.2f}",
                "n_escalations": len(px.escalations),
                "compounding": px.compounding,
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
    result = pd.DataFrame(rows)
    for col in (
        "n_escalations",
        "price_page",
        "escalation_page",
        "amendment_page",
        "discount_page",
    ):
        if col in result:  # REVIEW rows leave these blank; keep them integers, not floats
            result[col] = pd.to_numeric(result[col]).astype("Int64")
    if result.empty:
        result = pd.DataFrame(
            columns=[*invoices.columns, "source_row", "status", "issue_type", "reason"]
        )
    return result, pd.DataFrame(issues, columns=ISSUE_COLUMNS)


def reconcile(
    invoices: pd.DataFrame,
    adjustments: pd.DataFrame,
    terms: dict[str, ContractTerms],
    cpi: dict[int, Decimal],
) -> pd.DataFrame:
    return reconcile_with_issues(invoices, adjustments, terms, cpi)[0]


def run(terms_dir: Path, data_dir: Path = DATA, out_dir: Path = OUTPUT) -> pd.DataFrame:
    invoices, adjustments, cpi = read_inputs(data_dir)
    result, issues = reconcile_with_issues(invoices, adjustments, load_terms(terms_dir), cpi)
    out_dir.mkdir(parents=True, exist_ok=True)
    result.to_csv(out_dir / "line_results.csv", index=False)
    issues.to_csv(out_dir / "input_issues.csv", index=False)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--terms",
        required=True,
        help="Directory of ContractTerms JSON (data/extracted/rule, data/extracted/llm). "
        "data/eval/gold is the answer key: use it only for engine-only evaluation.",
    )
    args = ap.parse_args()
    result = run(Path(args.terms))
    under = (
        result.get("potential_underbilling", pd.Series(dtype=str))
        .replace("", "0")
        .fillna("0")
        .map(Decimal)
        .sum()
    )
    print(f"Reconciled {len(result)} lines using terms from {args.terms}")
    print(result["status"].value_counts().to_string())
    print(f"Potential underbilling: {under:,.2f} (synthetic data; not validated recovery)")


if __name__ == "__main__":
    main()
