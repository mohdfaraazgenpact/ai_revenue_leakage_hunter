"""Deterministic expected-price calculation from extracted contract terms.

Rules (see docs/decisions.md):
- The anchor price is the latest amendment price effective on/before the date, else the base price.
- Escalations apply on each anniversary of ``first_escalation_date`` strictly after the anchor
  date and on/before the invoice date (an amended price is inclusive of a same-day adjustment).
- Fixed escalation uses ``rate_pct``. CPI escalation uses CPI of the prior calendar year,
  clamped to [floor, cap].
- ``Escalation.compounding`` selects the convention: compounding multiplies each step onto the
  previous price; simple escalation applies the sum of the step rates to the anchor price.
- The exact result is rounded half-up to cents once. An approved discount is then applied and
  rounded again.
- An escalation clause whose first date or rate is unresolved raises ValueError, so the line goes to
  REVIEW instead of being priced as if the clause did not exist.
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
    compounding: bool = True
    currency: str = "USD"

    def formula(self) -> str:
        cur = self.currency
        parts = [f"{cur} {self.anchor_price:,.2f} ({self.anchor_source})"]
        if self.compounding or len(self.escalations) < 2:
            parts += [f"x (1 + {r}%) [{d.isoformat()}]" for d, r in self.escalations]
        else:
            steps = " + ".join(f"{r}% [{d.isoformat()}]" for d, r in self.escalations)
            parts.append(f"x (1 + {steps}) (simple, non-compounding)")
        s = " ".join(parts) + f" = {cur} {self.undiscounted_price:,.2f}"
        if self.discount_pct is not None:
            s += f"; less approved discount {self.discount_pct}% = {cur} {self.unit_price:,.2f}"
        return s


def escalate(anchor: Decimal, rates: list[Decimal], compounding: bool = True) -> Decimal:
    """Exact (unrounded) price after applying ``rates`` (percent) to ``anchor``."""
    anchor = Decimal(anchor)
    if not compounding:
        return anchor * (1 + sum(rates, Decimal("0")) / 100)
    for r in rates:
        anchor *= 1 + r / 100
    return anchor


def _rate(
    esc: Escalation, anniversary: date, cpi: dict[int, Decimal], override: Decimal | None
) -> Decimal:
    if override is not None:
        return override
    if esc.type == "fixed_pct":
        if esc.rate_pct is None:
            raise ValueError(
                "Fixed escalation clause has no resolved rate; contract terms need review"
            )
        return esc.rate_pct
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
    if esc.type != "none" and esc.first_escalation_date is None:
        raise ValueError(
            "Escalation clause found but its first escalation date was not resolved; "
            "contract terms need review"
        )
    if esc.type != "none":
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

    undiscounted = money(escalate(anchor_price, [r for _, r in steps], esc.compounding))
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
        esc.compounding,
        terms.currency,
    )
