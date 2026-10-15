import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.schema import ContractTerms


def _terms(**over):
    data = {
        "contract_id": "C-1",
        "customer_name": "Acme Industrial",
        "effective_date": "2024-01-01",
        "end_date": "2026-12-31",
        "prices": [{"sku": "SKU-A", "unit_price": "100.00"}],
        "escalation": {
            "type": "fixed_pct",
            "rate_pct": "3.5",
            "first_escalation_date": "2025-01-01",
        },
    }
    data.update(over)
    return ContractTerms.model_validate(data)


def test_money_round_trips_exactly_through_json():
    t = _terms()
    again = ContractTerms.model_validate(json.loads(t.model_dump_json()))
    assert again.prices[0].unit_price == Decimal("100.00")
    assert again.escalation.rate_pct == Decimal("3.5")


def test_invalid_date_rejected():
    with pytest.raises(ValidationError):
        _terms(effective_date="not a date")


def test_price_lookup():
    assert _terms().price_for("SKU-A").unit_price == Decimal("100.00")
    assert _terms().price_for("SKU-Z") is None
