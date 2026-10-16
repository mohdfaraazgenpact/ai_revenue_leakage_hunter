"""Regression guards for the v2 financial-control fixes (commit 63785e9).

Each test fails if a specific defect comes back. These cover boundaries that the original tests in
test_reconcile.py, test_price_schedule.py and test_evaluate.py do not. Every expected value is
computed by hand, not taken from the generator.
"""

from decimal import Decimal

import pandas as pd
import pytest

from src.evaluate import evaluate
from src.extract.rule_extractor import _compounding
from src.reconcile import reconcile_with_issues
from src.schema import ContractTerms


def _terms(escalation=None):
    return ContractTerms.model_validate(
        {
            "contract_id": "C-1",
            "customer_name": "Acme",
            "effective_date": "2024-01-01",
            "end_date": "2026-12-31",
            "prices": [{"sku": "S1", "unit_price": "100.00"}],
            "escalation": escalation
            or {"type": "fixed_pct", "rate_pct": "5", "first_escalation_date": "2025-01-01"},
        }
    )


def _inv(line_id, d, price, qty=10, **over):
    row = {
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
    return {**row, **over}


def _run(invoices, adjustments=(), terms=None):
    lines, issues = reconcile_with_issues(
        pd.DataFrame(invoices), pd.DataFrame(list(adjustments)), {"C-1": terms or _terms()}, {}
    )
    return lines.set_index("invoice_line_id"), issues


# ---- currency mismatch (D-013) ----
def test_currency_mismatch_reports_no_dollar_gap():
    # v1 compared EUR 95 with USD 105 and reported 100.00 of underbilling.
    r, _ = _run([_inv("L1", "2025-02-15", 95, currency="EUR")])
    assert r.loc["L1", "status"] == "REVIEW"
    assert pd.isna(r.loc["L1"].get("potential_underbilling"))


def test_currency_code_case_does_not_cause_a_false_mismatch():
    r, _ = _run([_inv("L1", "2025-02-15", 105, currency="usd")])
    assert r.loc["L1", "status"] == "MATCH"


# ---- duplicate billing (D-014) ----
def test_exact_duplicate_does_not_apply_the_adjustment_twice():
    row = _inv("L1", "2025-02-15", 100)
    adj = {"adjustment_id": "A1", "invoice_line_id": "L1", "adjustment_type": "debit_note"}
    lines, _ = reconcile_with_issues(
        pd.DataFrame([row, dict(row)]),
        pd.DataFrame([{**adj, "amount": "50.00", "quantity": ""}]),
        {"C-1": _terms()},
        {},
    )
    assert list(lines["status"]) == ["MATCH", "DUPLICATE"]
    assert lines["potential_underbilling"].replace("", "0").fillna("0").map(Decimal).sum() == 0


def test_exact_duplicate_prediction_is_not_scored_twice(tmp_path):
    truth = pd.DataFrame(
        [("L1", "C", "missed_escalation", "true", "50.00", "0.00", "UNDERBILLING")],
        columns=[
            "invoice_line_id",
            "contract_id",
            "scenario",
            "is_leakage",
            "seeded_leakage_amount",
            "seeded_overbilling_amount",
            "expected_outcome",
        ],
    )
    pred = pd.DataFrame(
        [
            ("L1", "POTENTIAL_UNDERBILLING", "", "50.00", "0.00"),
            ("L1", "DUPLICATE", "EXACT_DUPLICATE", "50.00", "0.00"),
        ],
        columns=[
            "invoice_line_id",
            "status",
            "issue_type",
            "potential_underbilling",
            "potential_overbilling",
        ],
    )
    (tmp_path / "out").mkdir()
    pred.to_csv(tmp_path / "out" / "line_results.csv", index=False)
    truth.to_csv(tmp_path / "ground_truth.csv", index=False)
    pd.DataFrame(columns=["contract_id", "scenario"]).to_csv(
        tmp_path / "contract_scenarios.csv", index=False
    )
    res = evaluate(out_dir=tmp_path / "out", eval_dir=tmp_path)
    assert res["tp"] == 1 and res["detected_usd"] == "50.00"


# ---- simple versus compound escalation (D-010) ----
def test_simple_escalation_flows_through_reconciliation():
    simple = {
        "type": "fixed_pct",
        "rate_pct": "5",
        "first_escalation_date": "2025-01-01",
        "compounding": False,
    }
    r, _ = _run([_inv("L1", "2026-02-15", 100)], terms=_terms(simple))
    assert r.loc["L1", "expected_unit_price"] == "110.00"  # compounding would give 110.25
    assert r.loc["L1", "potential_underbilling"] == "100.00"
    assert not r.loc["L1", "compounding"]


@pytest.mark.parametrize(
    "clause,compounding",
    [
        ("The Unit Price shall increase by 5% annually.", True),  # silent -> D-004 default
        ("Prices increase by 4% per year on a non-compounding basis.", False),
        ("A simple annual increase of 3% applies.", False),
        ("Each year the price rises by 5% of the original Unit Price.", False),
    ],
)
def test_rule_extractor_reads_the_escalation_convention(clause, compounding):
    assert _compounding(clause) is compounding


# ---- unsupported adjustments (D-012) ----
def test_adjustment_on_an_unknown_line_is_logged_and_other_lines_still_price():
    adj = {
        "adjustment_id": "A9",
        "invoice_line_id": "LX",
        "adjustment_type": "credit_note",
        "amount": "10.00",
        "quantity": "",
    }
    r, issues = _run([_inv("L1", "2025-02-15", 105)], [adj])
    assert r.loc["L1", "status"] == "MATCH"
    row = issues.iloc[0]
    assert (row["record_id"], row["issue_type"]) == ("A9", "ADJUSTMENT_ISSUE")
    assert "unknown invoice line" in row["detail"]


def test_return_of_more_units_than_invoiced_goes_to_review():
    adj = {
        "adjustment_id": "A1",
        "invoice_line_id": "L1",
        "adjustment_type": "return_credit",
        "amount": "1100.00",
        "quantity": "11",
    }
    r, _ = _run([_inv("L1", "2024-06-15", 100)], [adj])
    assert r.loc["L1", "issue_type"] == "ADJUSTMENT_ISSUE"


# ---- malformed inputs (D-011) ----
@pytest.mark.parametrize(
    "field,value",
    [
        ("quantity", "nan"),
        ("quantity", "inf"),
        ("invoiced_unit_price", "Infinity"),
        ("invoice_date", "2025-02-30"),
        ("invoice_date", "2025-2-15"),
        ("contract_id", "   "),
        ("currency", "US$"),
    ],
)
def test_non_finite_numbers_impossible_dates_and_blank_ids_are_quarantined(field, value):
    r, issues = _run([_inv("BAD", "2025-02-15", 100, **{field: value})])
    assert r.loc["BAD", "issue_type"] == "INVALID_INPUT"
    assert pd.isna(r.loc["BAD"].get("potential_underbilling"))
    assert field in issues.iloc[0]["detail"]


# ---- invoice arithmetic (D-015) ----
@pytest.mark.parametrize(
    "amount,issue",
    [("1000.01", ""), ("999.99", ""), ("1000.02", "ARITHMETIC_MISMATCH")],
)
def test_arithmetic_tolerance_is_one_cent(amount, issue):
    r, _ = _run([_inv("L1", "2024-06-15", 100, invoiced_line_amount=amount)])
    assert r.loc["L1", "issue_type"] == issue
    if not issue:
        assert r.loc["L1", "status"] == "MATCH"


# ---- unresolved terms (D-016) ----
@pytest.mark.parametrize(
    "escalation",
    [
        {"type": "fixed_pct", "first_escalation_date": "2025-01-01"},  # rate missing
        {"type": "cpi", "first_escalation_date": "2025-01-01"},  # CPI year not in the table
    ],
)
def test_unresolved_rate_or_missing_index_routes_to_review(escalation):
    r, _ = _run([_inv("L1", "2025-02-15", 100)], terms=_terms(escalation))
    assert r.loc["L1", "status"] == "REVIEW"
    assert r.loc["L1", "issue_type"] == "TERMS_NOT_DETERMINABLE"


def test_unresolved_terms_do_not_affect_lines_before_the_escalation():
    esc = {"type": "fixed_pct", "first_escalation_date": "2025-01-01"}
    r, _ = _run([_inv("L1", "2024-06-15", 100)], terms=_terms(esc))
    assert r.loc["L1", "status"] == "MATCH"
