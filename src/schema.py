"""Canonical contract-terms schema.

Every extractor (gold, rule-based, LLM, manual) must emit a ``ContractTerms`` object.
Money and percentages are Decimal so that downstream arithmetic is exact; the LLM never
produces amounts that are used without passing through this schema.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

KEY_FIELDS = (
    "customer_name",
    "effective_date",
    "end_date",
    "prices",
    "escalation.type",
    "escalation.rate_pct",
    "escalation.first_escalation_date",
    "amendments",
)


class Citation(BaseModel):
    """Where in the source document a value was found."""

    clause_id: str | None = None
    page: int | None = None
    quote: str = Field(description="Verbatim text from the contract supporting the value")
    verified: bool | None = Field(
        default=None, description="Set by the citation verifier, never by the extractor"
    )


class SkuPrice(BaseModel):
    sku: str
    description: str | None = None
    unit_price: Decimal
    citation: Citation | None = None


class Escalation(BaseModel):
    type: Literal["none", "fixed_pct", "cpi"] = "none"
    rate_pct: Decimal | None = Field(default=None, description="Fixed annual % (fixed_pct)")
    cap_pct: Decimal | None = Field(default=None, description="Max annual % (cpi)")
    floor_pct: Decimal | None = Field(default=None, description="Min annual % (cpi)")
    first_escalation_date: date | None = None
    frequency: Literal["annual"] = "annual"
    compounding: bool = True
    citation: Citation | None = None


class Amendment(BaseModel):
    amendment_id: str
    effective_date: date
    sku: str | None = Field(default=None, description="None means the change applies to all SKUs")
    new_unit_price: Decimal | None = None
    new_escalation_rate_pct: Decimal | None = None
    citation: Citation | None = None


class ApprovedDiscount(BaseModel):
    sku: str | None = None
    discount_pct: Decimal
    start_date: date
    end_date: date
    citation: Citation | None = None


class ContractTerms(BaseModel):
    contract_id: str
    customer_name: str
    customer_id: str | None = None
    currency: str = "USD"
    effective_date: date
    end_date: date
    prices: list[SkuPrice]
    escalation: Escalation = Escalation()
    amendments: list[Amendment] = []
    approved_discounts: list[ApprovedDiscount] = []
    field_confidence: dict[str, float] = {}
    source: Literal["gold", "rule", "llm", "manual"] = "manual"
    prompt_version: str | None = None

    def price_for(self, sku: str) -> SkuPrice | None:
        return next((p for p in self.prices if p.sku == sku), None)
