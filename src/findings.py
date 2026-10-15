"""Aggregate line-level results into prioritized findings with a deterministic root cause.

Root causes (classified by testing which wrong price the billed price reproduces):
    MISSED_ESCALATION      billed at the anchor price, no escalations applied
    PARTIAL_ESCALATION     billed with some but not all due escalations
    AMENDMENT_NOT_APPLIED  billed at the price that would apply without the amendment
    PRICE_BELOW_CONTRACT   billed below the contract price for any other reason
    OVERBILLING            billed above contract (reported separately, never netted)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from src.price_schedule import expected_price, money
from src.schema import ContractTerms

AS_OF = date(2026, 1, 31)  # analysis date for recoverability ageing

OWNERS = {
    "MISSED_ESCALATION": (
        "Pricing & Billing Master Data",
        "Load the escalated Unit Price into the billing price master from {first_date}; "
        "prepare a supplementary invoice for the under-billed lines for approval.",
    ),
    "PARTIAL_ESCALATION": (
        "Pricing & Billing Master Data",
        "Apply the missing anniversary escalation in the price master from {first_date}; "
        "prepare a supplementary invoice for the under-billed lines for approval.",
    ),
    "AMENDMENT_NOT_APPLIED": (
        "Contract Administration",
        "Load the amended Unit Price into the price master effective {first_date}; "
        "confirm the amendment is countersigned, then prepare a rebill for approval.",
    ),
    "PRICE_BELOW_CONTRACT": (
        "Billing Operations & Sales Operations",
        "Correct the Unit Price in the price master; check with the account owner that no "
        "undocumented concession exists before preparing a rebill.",
    ),
    "OVERBILLING": (
        "Billing Operations",
        "Verify and issue a credit note to the customer for the over-billed amount.",
    ),
}


def classify_line(terms: ContractTerms, row: dict, cpi) -> str:
    if row["status"] == "POTENTIAL_OVERBILLING":
        return "OVERBILLING"
    billed = money(row["invoiced_unit_price"])
    d = date.fromisoformat(row["invoice_date"])
    px = expected_price(terms, row["sku"], d, cpi)
    if px.escalations and billed == money(px.anchor_price):
        return "MISSED_ESCALATION"
    if px.anchor_source != "base price":
        no_am = terms.model_copy(update={"amendments": []})
        if billed == expected_price(no_am, row["sku"], d, cpi).unit_price:
            return "AMENDMENT_NOT_APPLIED"
    if len(px.escalations) >= 2:
        exact = px.anchor_price
        for _, r in px.escalations[:-1]:
            exact *= 1 + r / 100
            if billed == money(exact):
                return "PARTIAL_ESCALATION"
    return "PRICE_BELOW_CONTRACT"


def _recoverability(dates: list[date], amounts: list[Decimal]) -> Decimal:
    """Share of value still comfortably inside a typical 24-month claim window."""
    total = sum(amounts) or Decimal("1")
    w = Decimal("0")
    for d, a in zip(dates, amounts, strict=True):
        age_m = (AS_OF.year - d.year) * 12 + AS_OF.month - d.month
        w += a * (
            Decimal("1") if age_m <= 12 else Decimal("0.6") if age_m <= 24 else Decimal("0.2")
        )
    return (w / total).quantize(Decimal("0.001"))


def _page(v) -> int | None:
    return None if v is None or pd.isna(v) else int(v)


@dataclass
class Finding:
    finding_id: str
    contract_id: str
    customer_id: str
    customer_name: str
    sku: str
    root_cause: str
    line_count: int
    first_date: str
    last_date: str
    amount: Decimal
    recoverability: Decimal
    recoverable_estimate: Decimal
    extraction_confidence: float
    priority_score: float
    expected_unit_price_latest: str
    billed_unit_price_latest: str
    calculation_latest: str
    owner: str
    recommended_action: str
    invoice_line_ids: list[str]
    evidence: dict
    headline: str = ""
    narrative: str = ""
    rebill_note: str = ""
    explanation_source: str = ""
    guardrail_note: str = ""


def build_findings(
    lines: pd.DataFrame,
    terms: dict[str, ContractTerms],
    cpi,
    customers: dict[str, str] | None = None,
) -> list[Finding]:
    customers = customers or {}
    flagged = lines[
        lines["status"].isin(["POTENTIAL_UNDERBILLING", "POTENTIAL_OVERBILLING"])
    ].copy()
    if flagged.empty:
        return []
    flagged["root_cause"] = [
        classify_line(terms[r["contract_id"]], r, cpi) for r in flagged.to_dict(orient="records")
    ]
    findings: list[Finding] = []
    for (cid, sku, cause), g in flagged.groupby(["contract_id", "sku", "root_cause"], sort=False):
        g = g.sort_values("invoice_date")
        col = "potential_overbilling" if cause == "OVERBILLING" else "potential_underbilling"
        amounts = [Decimal(x) for x in g[col]]
        dates = [date.fromisoformat(x) for x in g["invoice_date"]]
        amount = sum(amounts)
        rec = _recoverability(dates, amounts)
        conf = float(g["extraction_confidence"].astype(float).min())
        last = g.iloc[-1]
        owner, action = OWNERS[cause]
        evidence = {
            k: {
                "clause_id": last.get(f"{k}_clause_id"),
                "page": _page(last.get(f"{k}_page")),
                "quote": last.get(f"{k}_quote"),
            }
            for k in ("price", "escalation", "amendment", "discount")
            if isinstance(last.get(f"{k}_quote"), str) and last.get(f"{k}_quote")
        }
        findings.append(
            Finding(
                finding_id="",
                contract_id=cid,
                customer_id=last["customer_id"],
                customer_name=customers.get(last["customer_id"], last["customer_id"]),
                sku=sku,
                root_cause=cause,
                line_count=len(g),
                first_date=g.iloc[0]["invoice_date"],
                last_date=last["invoice_date"],
                amount=money(amount),
                recoverability=rec,
                recoverable_estimate=money(amount * rec),
                extraction_confidence=round(conf, 3),
                priority_score=0.0
                if cause == "OVERBILLING"
                else round(float(amount * rec) * conf, 2),
                expected_unit_price_latest=last["expected_unit_price"],
                billed_unit_price_latest=last["invoiced_unit_price"],
                calculation_latest=last["calculation"],
                owner=owner,
                recommended_action=action.format(first_date=g.iloc[0]["invoice_date"]),
                invoice_line_ids=list(g["invoice_line_id"]),
                evidence=evidence,
            )
        )
    findings.sort(key=lambda f: (f.root_cause == "OVERBILLING", -f.priority_score))
    for i, f in enumerate(findings, start=1):
        f.finding_id = f"F-{i:03d}"
    return findings


def findings_frame(findings: list[Finding]) -> pd.DataFrame:
    rows = []
    for f in findings:
        d = dict(f.__dict__)
        d["invoice_line_ids"] = ";".join(f.invoice_line_ids)
        d["evidence_clauses"] = ";".join(f"{k}:{v['clause_id']}" for k, v in f.evidence.items())
        d.pop("evidence")
        rows.append(d)
    return pd.DataFrame(rows)
