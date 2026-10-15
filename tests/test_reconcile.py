from decimal import Decimal

import pandas as pd

from src.reconcile import reconcile
from src.schema import ContractTerms


def _terms():
    return ContractTerms.model_validate(
        {
            "contract_id": "C-1",
            "customer_name": "Acme",
            "effective_date": "2024-01-01",
            "end_date": "2026-12-31",
            "prices": [
                {
                    "sku": "S1",
                    "unit_price": "100.00",
                    "citation": {"clause_id": "A.1", "quote": "S1 USD 100"},
                }
            ],
            "escalation": {
                "type": "fixed_pct",
                "rate_pct": "5",
                "first_escalation_date": "2025-01-01",
                "citation": {"clause_id": "4.2", "quote": "increase by 5%"},
            },
        }
    )


def _inv(line_id, d, price, qty=10):
    return {
        "invoice_line_id": line_id,
        "invoice_id": "I",
        "invoice_date": d,
        "customer_id": "CU",
        "contract_id": "C-1",
        "sku": "S1",
        "quantity": str(qty),
        "invoiced_unit_price": f"{price:.2f}",
        "invoiced_line_amount": f"{Decimal(str(price)) * qty:.2f}",
        "currency": "USD",
    }


def _run(invoices, adjustments=None):
    adj = pd.DataFrame(adjustments or [], columns=["invoice_line_id", "adjustment_type", "amount"])
    return reconcile(pd.DataFrame(invoices), adj, {"C-1": _terms()}, {}).set_index(
        "invoice_line_id"
    )


def test_missed_escalation_flagged_with_evidence():
    r = _run([_inv("L1", "2024-06-15", 100), _inv("L2", "2025-02-15", 100)])
    assert r.loc["L1", "status"] == "MATCH"
    assert r.loc["L2", "status"] == "POTENTIAL_UNDERBILLING"
    assert r.loc["L2", "potential_underbilling"] == "50.00"
    assert r.loc["L2", "escalation_clause_id"] == "4.2"
    assert r.loc["L2", "price_clause_id"] == "A.1"


def test_debit_note_restores_underbilled_line():
    r = _run(
        [_inv("L1", "2025-02-15", 100)],
        [{"invoice_line_id": "L1", "adjustment_type": "debit_note", "amount": "50.00"}],
    )
    assert r.loc["L1", "status"] == "MATCH"


def test_overbilling_reported_separately_not_netted():
    r = _run([_inv("L1", "2025-02-15", 110), _inv("L2", "2025-03-15", 100)])
    assert r.loc["L1", "status"] == "POTENTIAL_OVERBILLING"
    assert r.loc["L1", "potential_underbilling"] == "0.00"
    assert r.loc["L2", "potential_underbilling"] == "50.00"


def test_unknown_sku_and_out_of_term_go_to_review():
    bad_sku = dict(_inv("L1", "2025-02-15", 100), sku="ZZZ")
    late = _inv("L2", "2027-02-15", 100)
    r = _run([bad_sku, late])
    assert (r["status"] == "REVIEW").all()


def test_missing_contract_terms_go_to_review():
    inv = dict(_inv("L1", "2025-02-15", 100), contract_id="C-404")
    r = reconcile(
        pd.DataFrame([inv]),
        pd.DataFrame(columns=["invoice_line_id", "adjustment_type", "amount"]),
        {"C-1": _terms()},
        {},
    )
    assert r.iloc[0]["status"] == "REVIEW"
