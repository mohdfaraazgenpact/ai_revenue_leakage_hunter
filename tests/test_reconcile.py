from decimal import Decimal

import pandas as pd
import pytest

from src.reconcile import reconcile, reconcile_with_issues
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


# ---- data integrity regressions (vetting FIN-09, FIN-14, FIN-15, EXT-02..05, OPS-03) ----
def _adj(**kw):
    return {"adjustment_id": "A1", "invoice_line_id": "L1", "quantity": "", **kw}


def test_currency_mismatch_goes_to_review_not_underbilling():
    r = _run([dict(_inv("L1", "2025-02-15", 95), currency="EUR")])
    assert r.loc["L1", "status"] == "REVIEW"
    assert r.loc["L1", "issue_type"] == "CURRENCY_MISMATCH"


def test_exact_duplicate_row_is_counted_once():
    row = _inv("L1", "2025-02-15", 100)
    r = reconcile(pd.DataFrame([row, dict(row)]), pd.DataFrame(), {"C-1": _terms()}, {})
    assert list(r["status"]) == ["POTENTIAL_UNDERBILLING", "DUPLICATE"]
    assert r["potential_underbilling"].fillna("0").map(Decimal).sum() == Decimal("50.00")


def test_conflicting_rows_with_same_id_all_go_to_review():
    a, b = _inv("L1", "2025-02-15", 100), _inv("L1", "2025-02-15", 90)
    r = reconcile(pd.DataFrame([a, b]), pd.DataFrame(), {"C-1": _terms()}, {})
    assert set(r["status"]) == {"REVIEW"} and set(r["issue_type"]) == {"DUPLICATE_ID_CONFLICT"}


def test_same_business_key_under_new_id_is_a_possible_duplicate():
    a = _inv("L1", "2025-02-15", 100)
    b = dict(a, invoice_line_id="L2")
    r = _run([a, b])
    assert r.loc["L1", "status"] == "POTENTIAL_UNDERBILLING"
    assert r.loc["L2", "issue_type"] == "POSSIBLE_DUPLICATE"


def test_line_amount_must_equal_quantity_times_unit_price():
    r = _run([dict(_inv("L1", "2025-02-15", 95), invoiced_line_amount="960.00")])
    assert r.loc["L1", "issue_type"] == "ARITHMETIC_MISMATCH"


@pytest.mark.parametrize(
    "field,value",
    [
        ("invoice_date", "15/06/2025"),
        ("invoice_date", ""),
        ("invoiced_line_amount", ""),
        ("quantity", "abc"),
        ("quantity", "-5"),
        ("invoiced_unit_price", "-100"),
        ("currency", ""),
    ],
)
def test_malformed_rows_are_quarantined_and_the_rest_still_reconcile(field, value):
    bad = dict(_inv("BAD", "2025-02-15", 100), **{field: value})
    lines, issues = reconcile_with_issues(
        pd.DataFrame([bad, _inv("OK", "2025-02-15", 105)]), pd.DataFrame(), {"C-1": _terms()}, {}
    )
    lines = lines.set_index("invoice_line_id")
    assert lines.loc["BAD", "issue_type"] == "INVALID_INPUT"
    assert lines.loc["OK", "status"] == "MATCH"
    row = issues[issues["record_id"] == "BAD"].iloc[0]
    assert row["source_file"] == "invoice_lines.csv" and row["source_row"] == 2
    assert field in row["detail"]


def test_credit_note_reduces_net_and_return_credit_reduces_expected_quantity():
    lines = [_inv("L1", "2024-06-15", 100), dict(_inv("L2", "2024-06-15", 100), invoice_id="I2")]
    adj = pd.DataFrame(
        [
            _adj(adjustment_type="credit_note", amount="40.00"),
            _adj(
                adjustment_id="A2",
                invoice_line_id="L2",
                adjustment_type="return_credit",
                amount="200.00",
                quantity="2",
            ),
        ]
    )
    r = reconcile(
        pd.DataFrame(lines),
        adj,
        {"C-1": _terms()},
        {},
    ).set_index("invoice_line_id")
    assert r.loc["L1", "potential_underbilling"] == "40.00"
    assert r.loc["L2", "status"] == "MATCH" and r.loc["L2", "expected_line_amount"] == "800.00"


@pytest.mark.parametrize(
    "adj",
    [
        {"adjustment_type": "write_off", "amount": "10.00"},
        {"adjustment_type": "credit_note", "amount": "-10.00"},
        {"adjustment_type": "credit_note", "amount": ""},
        {"adjustment_type": "return_credit", "amount": "100.00", "quantity": ""},
    ],
)
def test_unsupported_or_malformed_adjustments_send_the_line_to_review(adj):
    lines, issues = reconcile_with_issues(
        pd.DataFrame([_inv("L1", "2024-06-15", 100)]),
        pd.DataFrame([_adj(**adj)]),
        {"C-1": _terms()},
        {},
    )
    assert lines.iloc[0]["issue_type"] == "ADJUSTMENT_ISSUE"
    assert issues.iloc[0]["source_file"] == "billing_adjustments.csv"


def test_unresolved_escalation_terms_route_to_review():
    t = _terms().model_copy(
        update={
            "escalation": _terms().escalation.model_copy(update={"first_escalation_date": None})
        }
    )
    r = reconcile(pd.DataFrame([_inv("L1", "2025-02-15", 100)]), pd.DataFrame(), {"C-1": t}, {})
    assert r.iloc[0]["issue_type"] == "TERMS_NOT_DETERMINABLE"
