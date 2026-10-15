from datetime import date
from decimal import Decimal

import pytest

from src.price_schedule import expected_price
from src.schema import ContractTerms


def terms(**over):
    data = {
        "contract_id": "C-1",
        "customer_name": "Acme",
        "effective_date": "2024-01-01",
        "end_date": "2026-12-31",
        "prices": [{"sku": "S1", "unit_price": "100.00"}, {"sku": "S2", "unit_price": "10.00"}],
        "escalation": {"type": "fixed_pct", "rate_pct": "5", "first_escalation_date": "2025-01-01"},
    }
    data.update(over)
    return ContractTerms.model_validate(data)


def p(t, d, sku="S1", cpi=None):
    return expected_price(t, sku, date.fromisoformat(d), cpi or {}).unit_price


def test_escalation_applies_on_anniversary_and_compounds():
    t = terms()
    assert p(t, "2024-12-31") == Decimal("100.00")
    assert p(t, "2025-01-01") == Decimal("105.00")
    assert p(t, "2026-01-01") == Decimal("110.25")


def test_rounding_once_after_exact_compounding():
    t = terms(
        prices=[{"sku": "S1", "unit_price": "33.33"}],
        escalation={"type": "fixed_pct", "rate_pct": "3.5", "first_escalation_date": "2025-01-01"},
    )
    # 33.33 * 1.035 * 1.035 = 35.7039... -> 35.70 (not rounded per step)
    assert p(t, "2026-06-01") == Decimal("35.70")


def test_leap_day_anniversary_falls_back_to_28_february():
    t = terms(
        effective_date="2023-02-28",
        escalation={"type": "fixed_pct", "rate_pct": "5", "first_escalation_date": "2024-02-29"},
    )
    assert p(t, "2025-02-27") == Decimal("105.00")
    assert p(t, "2025-02-28") == Decimal("110.25")


def test_cpi_clamped_to_floor_and_cap():
    t = terms(
        escalation={
            "type": "cpi",
            "floor_pct": "2",
            "cap_pct": "4",
            "first_escalation_date": "2025-01-01",
        }
    )
    assert p(t, "2025-06-01", cpi={2024: Decimal("6.5")}) == Decimal("104.00")  # capped
    assert p(t, "2025-06-01", cpi={2024: Decimal("1.0")}) == Decimal("102.00")  # floored
    assert p(t, "2025-06-01", cpi={2024: Decimal("2.9")}) == Decimal("102.90")


def test_amendment_resets_anchor_and_later_escalations_apply():
    t = terms(
        amendments=[
            {
                "amendment_id": "AM1",
                "effective_date": "2025-06-01",
                "sku": "S1",
                "new_unit_price": "120.00",
            }
        ]
    )
    assert p(t, "2025-05-31") == Decimal("105.00")
    assert p(t, "2025-06-01") == Decimal("120.00")
    assert p(t, "2026-01-01") == Decimal("126.00")
    assert p(t, "2026-01-01", sku="S2") == Decimal("11.03")  # other SKU unaffected (10 * 1.05^2)


def test_same_day_amendment_is_inclusive_of_escalation():
    t = terms(
        amendments=[
            {
                "amendment_id": "AM1",
                "effective_date": "2025-01-01",
                "sku": "S1",
                "new_unit_price": "120.00",
            }
        ]
    )
    assert p(t, "2025-01-01") == Decimal("120.00")


def test_approved_discount_only_inside_window():
    t = terms(
        approved_discounts=[
            {
                "sku": "S1",
                "discount_pct": "10",
                "start_date": "2025-03-01",
                "end_date": "2025-05-31",
            }
        ]
    )
    assert p(t, "2025-02-28") == Decimal("105.00")
    assert p(t, "2025-03-15") == Decimal("94.50")
    assert p(t, "2025-06-01") == Decimal("105.00")


def test_outside_term_and_unknown_sku_raise():
    with pytest.raises(ValueError):
        p(terms(), "2027-01-01")
    with pytest.raises(KeyError):
        p(terms(), "2025-01-01", sku="NOPE")
