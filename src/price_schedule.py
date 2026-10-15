"""Deterministic expected-price calculation from extracted contract terms.

Rules (see docs/decisions.md):
- The anchor price is the latest amendment price effective on/before the date, else the base price.
- Escalations apply on each anniversary of ``first_escalation_date`` strictly after the anchor
  date and on/before the invoice date (an amended price is inclusive of a same-day adjustment).
- Fixed escalation uses ``rate_pct``. CPI escalation uses CPI of the prior calendar year,
  clamped to [floor, cap].
- Compounding is exact, and the unit price is rounded half-up to cents once. An approved discount
  is then applied and rounded again.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from src.schema import Citation, ContractTerms, Escalation

CENT = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def add_years(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year + n)
    except ValueError:
        return d.replace(year=d.year + n, day=28)


def load_cpi(path: Path) -> dict[int, Decimal]:
    with Path(path).open(encoding="utf-8") as f:
        return {int(r["year"]): Decimal(r["cpi_pct"]) for r in csv.DictReader(f)}


@dataclass
class PriceExplanation:
    unit_price: Decimal  # final expected unit price (after any discount)
    undiscounted_price: Decimal
    anchor_price: Decimal
    anchor_date: date
    anchor_source: str  # "base" or amendment id
    escalations: list[tuple[date, Decimal]] = field(default_factory=list)
    discount_pct: Decimal | None = None
    citations: dict[str, Citation] = field(default_factory=dict)

    def formula(self) -> str:
        parts = [f"USD {self.anchor_price:,.2f} ({self.anchor_source})"]
        parts += [f"x (1 + {r}%) [{d.isoformat()}]" for d, r in self.escalations]
        s = " ".join(parts) + f" = USD {self.undiscounted_price:,.2f}"
        if self.discount_pct is not None:
            s += f"; less approved discount {self.discount_pct}% = USD {self.unit_price:,.2f}"
        return s


def _rate(
    esc: Escalation, anniversary: date, cpi: dict[int, Decimal], override: Decimal | None
) -> Decimal:
    if override is not None:
        return override
    if esc.type == "fixed_pct":
        return esc.rate_pct or Decimal("0")
    if esc.type == "cpi":
        value = cpi.get(anniversary.year - 1)
        if value is None:
            raise ValueError(f"No CPI value for {anniversary.year - 1}")
        if esc.floor_pct is not None:
            value = max(value, esc.floor_pct)
        if esc.cap_pct is not None:
            value = min(value, esc.cap_pct)
        return value
    return Decimal("0")


def expected_price(
    terms: ContractTerms, sku: str, d: date, cpi: dict[int, Decimal] | None = None
) -> PriceExplanation:
    """Expected unit price for ``sku`` on date ``d``. Raises KeyError/ValueError when not determinable."""
    cpi = cpi or {}
    if not terms.effective_date <= d <= terms.end_date:
        raise ValueError(
            f"{d} is outside the contract term {terms.effective_date}..{terms.end_date}"
        )
    base = terms.price_for(sku)
    if base is None:
        raise KeyError(f"SKU {sku} not priced in contract {terms.contract_id}")

    cites: dict[str, Citation] = {}
    if base.citation:
        cites["price"] = base.citation
    anchor_price, anchor_date, anchor_source = base.unit_price, terms.effective_date, "base price"
    amendments = sorted(
        (a for a in terms.amendments if a.sku in (None, sku) and a.effective_date <= d),
        key=lambda a: a.effective_date,
    )
    priced = [a for a in amendments if a.new_unit_price is not None]
    if priced:
        a = priced[-1]
        anchor_price, anchor_date, anchor_source = (
            a.new_unit_price,
            a.effective_date,
            a.amendment_id,
        )
        if a.citation:
            cites["amendment"] = a.citation

    esc = terms.escalation
    steps: list[tuple[date, Decimal]] = []
    if esc.type != "none" and esc.first_escalation_date:
        if esc.citation:
            cites["escalation"] = esc.citation
        k = 0
        while (ann := add_years(esc.first_escalation_date, k)) <= d:
            if ann > anchor_date:
                override = next(
                    (
                        a.new_escalation_rate_pct
                        for a in reversed(amendments)
                        if a.new_escalation_rate_pct is not None and a.effective_date <= ann
                    ),
                    None,
                )
                steps.append((ann, _rate(esc, ann, cpi, override)))
            k += 1

    exact = Decimal(anchor_price)
    for _, r in steps:
        exact *= 1 + r / 100
    undiscounted = money(exact)
    final, disc_pct = undiscounted, None
    for disc in terms.approved_discounts:
        if disc.sku in (None, sku) and disc.start_date <= d <= disc.end_date:
            disc_pct = disc.discount_pct
            final = money(undiscounted * (1 - disc.discount_pct / 100))
            if disc.citation:
                cites["discount"] = disc.citation
    return PriceExplanation(
        final,
        undiscounted,
        Decimal(anchor_price),
        anchor_date,
        anchor_source,
        steps,
        disc_pct,
        cites,
    )
