"""Synthetic data factory v2: contracts (PDF/DOCX), invoices, billing adjustments and ground truth.

Outputs
    data/contracts/<id>.pdf|.docx        engine input: contract documents
    data/invoice_lines.csv               engine input: ERP invoice lines
    data/billing_adjustments.csv         engine input: debit/credit notes linked to lines
    data/customers.csv                   engine input: customer master
    data/reference/cpi_annual_pct.csv    engine input: synthetic CPI series
    data/eval/gold/<id>.json             evaluation only: true ContractTerms with citations
    data/eval/ground_truth.csv           evaluation only: line-level seeded leakage
    data/eval/expected_price_schedule.csv evaluation only: true price timeline per contract x SKU
    data/eval/contract_scenarios.csv     evaluation only: seeded scenario per contract

The ground-truth price timeline is computed here with an event-driven method that is
deliberately independent of ``src/price_schedule.py`` so the engine is not graded
against its own logic.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import shutil
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from src.contract_docs import build_contract, render_docx, render_pdf
from src.schema import (
    Amendment,
    ApprovedDiscount,
    Citation,
    ContractTerms,
    Escalation,
    SkuPrice,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SEED = 42
INVOICE_START, INVOICE_END = date(2024, 1, 1), date(2025, 12, 31)
CENT = Decimal("0.01")
# Synthetic CPI-U style annual inflation (%) by calendar year. Illustrative only.
CPI = {2022: Decimal("6.5"), 2023: Decimal("3.4"), 2024: Decimal("2.9"), 2025: Decimal("2.7")}

CUSTOMERS = {
    "Manufacturing": [
        "Northwind Fabrication Ltd",
        "Ironvale Components Inc",
        "Crestline Tooling Co",
        "Redfield Castings LLC",
        "Harborview Plastics Inc",
        "Summit Gearworks Ltd",
        "Oakridge Metalforming Inc",
        "Pinecrest Hydraulics LLC",
        "Granite Bay Fasteners Inc",
        "Silverline Pumps Ltd",
    ],
    "Hi-Tech": [
        "Bluepeak Systems Inc",
        "Quantum Harbor Networks LLC",
        "Nimbus Edge Devices Inc",
        "Vertex Lattice Software Ltd",
        "Brightwave Semiconductors Inc",
        "Coralstone Data Inc",
        "Helix Arc Robotics LLC",
        "Lumen Forge Analytics Inc",
        "Stratos Grid Technologies Ltd",
        "Polaris Mesh Labs Inc",
    ],
    "Logistics": [
        "Meridian Freightways Inc",
        "Coastal Relay Logistics LLC",
        "Trailhead Distribution Co",
        "Bayfront Cold Chain Inc",
        "Keystone Parcel Services Ltd",
        "Northstar Intermodal LLC",
        "Riverbend Warehousing Inc",
        "Cascade Fleet Partners LLC",
        "Horizon Last-Mile Inc",
        "Evergreen Cargo Systems Ltd",
    ],
}
# sku, description, unit price range, monthly volume range
CATALOG = {
    "Manufacturing": [
        ("MFG-1001", "Precision bearing assembly", (45, 120), (300, 1200)),
        ("MFG-1002", "Hydraulic valve block", (180, 420), (60, 250)),
        ("MFG-1003", "Machined steel housing", (60, 160), (150, 600)),
        ("MFG-1004", "Industrial gasket kit", (12, 35), (800, 3000)),
        ("MFG-1005", "Servo motor unit", (350, 900), (25, 100)),
    ],
    "Hi-Tech": [
        ("HTC-2001", "Edge gateway device", (600, 1400), (15, 70)),
        ("HTC-2002", "Network switch 48-port", (1800, 3200), (5, 25)),
        ("HTC-2003", "Software subscription per seat", (90, 240), (80, 500)),
        ("HTC-2004", "Premium support per device", (40, 110), (120, 600)),
        ("HTC-2005", "Sensor module", (25, 70), (400, 2000)),
    ],
    "Logistics": [
        ("LOG-3001", "Full truckload lane per load", (1400, 2800), (15, 80)),
        ("LOG-3002", "Pallet storage per pallet-month", (18, 40), (600, 2400)),
        ("LOG-3003", "Last-mile parcel delivery", (6, 14), (2000, 10000)),
        ("LOG-3004", "Cold-chain handling per pallet", (55, 130), (120, 600)),
        ("LOG-3005", "Cross-dock handling per pallet", (9, 22), (800, 3200)),
    ],
}
SCENARIOS = (
    ["missed_escalation"] * 5
    + ["partial_escalation"] * 3
    + ["amendment_not_applied"] * 3
    + ["price_below_contract"] * 3
    + ["control"] * 7
    + ["control_no_escalation"] * 3
    + ["trap_approved_discount"] * 3
    + ["trap_billing_adjustment"] * 2
    + ["overbilling"] * 1
)


def money(x) -> Decimal:
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def add_years(d: date, n: int) -> date:
    try:
        return d.replace(year=d.year + n)
    except ValueError:  # 29 Feb
        return d.replace(year=d.year + n, day=28)


def month_iter(start: date, end: date):
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


# ------------------------------------------------------------------ contract specs
def make_specs(rng: random.Random) -> list[dict]:
    scen = SCENARIOS[:]
    rng.shuffle(scen)
    industries = ["Manufacturing", "Hi-Tech", "Logistics"]
    cpi_slots = {"control": 2, "missed_escalation": 1, "partial_escalation": 1}
    specs = []
    for i, scenario in enumerate(scen):
        ind = industries[i % 3]
        cust = CUSTOMERS[ind][i // 3]
        if scenario == "partial_escalation":
            eff = date(2023, rng.randint(1, 6), 1)
        else:
            y = rng.choice([2023, 2024])
            eff = date(y, rng.randint(1, 12 if y == 2023 else 6), rng.choice([1, 1, 1, 15]))
        end = add_years(eff, 3) - timedelta(days=1)
        first_esc = add_years(eff, 1)

        if scenario == "control_no_escalation":
            esc = {"type": "none"}
        elif cpi_slots.get(scenario, 0) > 0:
            cpi_slots[scenario] -= 1
            lo, hi = rng.choice([(Decimal("2"), Decimal("5")), (Decimal("1.5"), Decimal("4"))])
            esc = {
                "type": "cpi",
                "floor_pct": lo,
                "cap_pct": hi,
                "first_escalation_date": first_esc,
            }
        else:
            rate = rng.choice([Decimal(x) for x in ("2", "2.5", "3", "3.5", "4", "4.5", "5")])
            esc = {"type": "fixed_pct", "rate_pct": rate, "first_escalation_date": first_esc}
        if esc["type"] == "cpi":
            esc.setdefault("first_escalation_date", first_esc)

        n_sku = rng.choice([1, 2, 2, 3, 3, 4])
        skus = []
        for sku, desc, (plo, phi), (qlo, qhi) in rng.sample(CATALOG[ind], n_sku):
            price = Decimal(str(round(rng.uniform(plo, phi) * 4) / 4)).quantize(CENT)
            skus.append(
                {
                    "sku": sku,
                    "description": desc,
                    "unit_price": price,
                    "base_qty": rng.randint(qlo, qhi),
                }
            )

        variant = rng.randint(0, 1) if esc["type"] in ("none", "cpi") else rng.randint(1, 8)
        spec = {
            "contract_id": f"C-{2001 + i}",
            "customer_id": f"CU-{101 + i}",
            "customer_name": cust,
            "industry": ind,
            "scenario": scenario,
            "effective_date": eff,
            "end_date": end,
            "escalation": esc,
            "skus": skus,
            "amendments": [],
            "approved_discounts": [],
            "wording_variant": variant,
            "date_style": rng.randint(0, 1),
            "format": "docx" if i % 4 == 3 else "pdf",
            "invoice_day": rng.choice([5, 10, 15, 20, 25]),
        }
        if scenario == "amendment_not_applied" or (scenario == "control" and i % 3 == 0):
            target = rng.choice(skus)
            am_date = date(rng.choice([2024, 2025]), rng.randint(2, 6), 1)
            am_date = max(am_date, eff + timedelta(days=120))
            if am_date.month == first_esc.month and am_date.day == first_esc.day:
                am_date += timedelta(days=31)
            current = _truth_unit_price(
                spec, target["sku"], am_date - timedelta(days=1), apply_discount=False
            )
            new_price = (current * Decimal(str(1 + rng.uniform(0.05, 0.12))) * 2).quantize(
                Decimal("1")
            ) / 2
            spec["amendments"].append(
                {
                    "sku": target["sku"],
                    "effective_date": am_date,
                    "signed_date": am_date - timedelta(days=rng.randint(10, 40)),
                    "new_unit_price": money(new_price),
                }
            )
        if scenario == "trap_approved_discount":
            target = rng.choice(skus)
            start = date(rng.choice([2024, 2025]), rng.randint(1, 7), 1)
            start = max(start, date(eff.year, eff.month, 1) + timedelta(days=62))
            end_m = start.month + rng.randint(2, 5)
            end_d = date(start.year + (end_m - 1) // 12, (end_m - 1) % 12 + 1, 1) - timedelta(
                days=1
            )
            spec["approved_discounts"].append(
                {
                    "sku": target["sku"],
                    "start_date": start,
                    "end_date": end_d,
                    "discount_pct": rng.choice([Decimal("5"), Decimal("7.5"), Decimal("10")]),
                }
            )
        specs.append(spec)
    return specs


# ------------------------------------------------------------------ ground truth pricing
def _rate_for_anniversary(esc: dict, anniv: date) -> Decimal:
    if esc["type"] == "fixed_pct":
        return esc["rate_pct"]
    cpi = CPI[anniv.year - 1]
    return min(max(cpi, esc["floor_pct"]), esc["cap_pct"])


def truth_timeline(spec: dict, sku: str) -> list[tuple[date, Decimal, str]]:
    """Event-driven list of (from_date, exact unit price, reason). Independent of the engine."""
    base = next(s for s in spec["skus"] if s["sku"] == sku)["unit_price"]
    events = []
    esc = spec["escalation"]
    if esc["type"] != "none":
        k, a = 0, esc["first_escalation_date"]
        while a <= spec["end_date"]:
            events.append((a, 1, "escalation"))
            k += 1
            a = add_years(esc["first_escalation_date"], k)
    for am in spec["amendments"]:
        if am["sku"] == sku:
            events.append(
                (am["effective_date"], 0, am)
            )  # amendment sorts before same-day escalation
    events.sort(key=lambda e: (e[0], e[1]))
    price = Decimal(base)
    timeline = [(spec["effective_date"], price, "base price")]
    for d, kind, payload in events:
        if kind == 0:
            price = Decimal(payload["new_unit_price"])
            timeline.append((d, price, "amendment"))
        else:
            if timeline[-1][0] == d and timeline[-1][2] == "amendment":
                continue  # amended price is inclusive of any adjustment due that day
            price = price * (1 + _rate_for_anniversary(esc, d) / 100)
            timeline.append((d, price, "escalation"))
    return timeline


def _truth_unit_price(spec, sku, d: date, apply_discount=True) -> Decimal:
    price = None
    for start, p, _ in truth_timeline(spec, sku):
        if start <= d:
            price = p
    unit = money(price)
    if apply_discount:
        for dsc in spec["approved_discounts"]:
            if dsc["sku"] == sku and dsc["start_date"] <= d <= dsc["end_date"]:
                unit = money(unit * (1 - dsc["discount_pct"] / 100))
    return unit


# ------------------------------------------------------------------ seeded billing behaviour
def billed_unit_price(spec, sku, d, rng_state) -> Decimal:
    sc = spec["scenario"]
    truth = _truth_unit_price(spec, sku, d)
    base = next(s for s in spec["skus"] if s["sku"] == sku)["unit_price"]
    esc = spec["escalation"]
    if sc == "missed_escalation":
        return base
    if sc == "partial_escalation":
        first = esc["first_escalation_date"]
        if d < first:
            return base
        return money(base * (1 + _rate_for_anniversary(esc, first) / 100))
    if sc == "amendment_not_applied":
        no_am = dict(spec, amendments=[])
        return _truth_unit_price(no_am, sku, d)
    if sc == "price_below_contract" and sku == rng_state["below_sku"]:
        wrong = dict(
            spec,
            skus=[
                dict(s, unit_price=rng_state["wrong_base"]) if s["sku"] == sku else s
                for s in spec["skus"]
            ],
        )
        return _truth_unit_price(wrong, sku, d)
    if (
        sc == "overbilling"
        and sku == rng_state["over_sku"]
        and d.strftime("%Y-%m") in rng_state["over_months"]
    ):
        return money(truth * Decimal("1.02"))
    if sc == "trap_billing_adjustment" and (d.strftime("%Y-%m"), sku) in rng_state["adj_lines"]:
        return base if base < truth else money(truth * Decimal("0.97"))
    return truth


def gold_terms(spec: dict, doc, pages: dict[str, int | None]) -> ContractTerms:
    def cite(key):
        cid, quote = doc.citations[key]
        return Citation(clause_id=cid, page=pages.get(quote), quote=quote)

    esc = spec["escalation"]
    return ContractTerms(
        contract_id=spec["contract_id"],
        customer_name=spec["customer_name"],
        customer_id=spec["customer_id"],
        currency="USD",
        effective_date=spec["effective_date"],
        end_date=spec["end_date"],
        prices=[
            SkuPrice(
                sku=s["sku"],
                description=s["description"],
                unit_price=s["unit_price"],
                citation=cite(f"price:{s['sku']}"),
            )
            for s in spec["skus"]
        ],
        escalation=Escalation(
            type=esc["type"],
            rate_pct=esc.get("rate_pct"),
            cap_pct=esc.get("cap_pct"),
            floor_pct=esc.get("floor_pct"),
            first_escalation_date=esc.get("first_escalation_date"),
            citation=cite("escalation"),
        ),
        amendments=[
            Amendment(
                amendment_id=f"AM{k}",
                effective_date=a["effective_date"],
                sku=a["sku"],
                new_unit_price=a["new_unit_price"],
                citation=cite(f"amendment:{k}"),
            )
            for k, a in enumerate(spec["amendments"], start=1)
        ],
        approved_discounts=[
            ApprovedDiscount(
                sku=d["sku"],
                discount_pct=d["discount_pct"],
                start_date=d["start_date"],
                end_date=d["end_date"],
                citation=cite(f"discount:{k}"),
            )
            for k, d in enumerate(spec["approved_discounts"], start=1)
        ],
        source="gold",
    )


def locate_pages(pdf_path: Path, quotes: list[str]) -> dict[str, int | None]:
    from src.extract.document_loader import load_document, normalize

    pages = load_document(pdf_path)
    out = {}
    for q in quotes:
        nq = normalize(q)
        out[q] = next((p.page for p in pages if nq in normalize(p.text)), None)
    return out


ADJ_FIELDS = [
    "adjustment_id",
    "invoice_line_id",
    "adjustment_type",
    "amount",
    "adjustment_date",
    "reason",
]


def write_csv(path: Path, rows: list[dict], fieldnames: list[str] | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames or list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main(data_dir: Path = DATA, n_contracts: int | None = None, seed: int = SEED) -> dict:
    rng = random.Random(seed)
    specs = make_specs(rng)[:n_contracts] if n_contracts else make_specs(rng)

    contracts_dir, eval_dir = data_dir / "contracts", data_dir / "eval"
    for d in (contracts_dir, eval_dir / "gold"):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)

    invoices, truth, adjustments, schedule_rows, scen_rows = [], [], [], [], []
    line_no, adj_no = 1, 1
    for spec in specs:
        doc = build_contract(spec)
        path = contracts_dir / f"{spec['contract_id']}.{spec['format']}"
        (render_docx if spec["format"] == "docx" else render_pdf)(doc, path)
        pages = locate_pages(path, [q for _, q in doc.citations.values()])
        gold = gold_terms(spec, doc, pages)
        (eval_dir / "gold" / f"{spec['contract_id']}.json").write_text(
            gold.model_dump_json(indent=2), encoding="utf-8"
        )

        months = [ym for ym in month_iter(max(INVOICE_START, spec["effective_date"]), INVOICE_END)]
        state = {
            "below_sku": rng.choice(spec["skus"])["sku"],
            "over_sku": rng.choice(spec["skus"])["sku"],
            "over_months": {f"{y}-{m:02d}" for y, m in rng.sample(months, min(4, len(months)))},
        }
        b = next(s for s in spec["skus"] if s["sku"] == state["below_sku"])["unit_price"]
        state["wrong_base"] = money(b * Decimal(str(1 - rng.choice([0.02, 0.03, 0.04]))))
        adj_targets = rng.sample(months[-12:], 3)
        state["adj_lines"] = {(f"{y}-{m:02d}", spec["skus"][0]["sku"]) for y, m in adj_targets}

        for s in spec["skus"]:
            for start, p, reason in truth_timeline(spec, s["sku"]):
                schedule_rows.append(
                    {
                        "contract_id": spec["contract_id"],
                        "sku": s["sku"],
                        "valid_from": start.isoformat(),
                        "unit_price_before_discount": f"{money(p):.2f}",
                        "reason": reason,
                    }
                )
        for y, m in months:
            d = date(y, m, spec["invoice_day"])
            if not spec["effective_date"] <= d <= spec["end_date"]:
                continue
            for s in spec["skus"]:
                qty = max(1, round(s["base_qty"] * rng.uniform(0.8, 1.2)))
                billed = billed_unit_price(spec, s["sku"], d, state)
                expected = _truth_unit_price(spec, s["sku"], d)
                line_id = f"IL-{line_no:05d}"
                billed_amt, exp_amt = money(billed * qty), money(expected * qty)
                invoices.append(
                    {
                        "invoice_line_id": line_id,
                        "invoice_id": f"INV-{spec['contract_id'][2:]}-{y}{m:02d}",
                        "invoice_date": d.isoformat(),
                        "customer_id": spec["customer_id"],
                        "contract_id": spec["contract_id"],
                        "sku": s["sku"],
                        "quantity": qty,
                        "invoiced_unit_price": f"{billed:.2f}",
                        "invoiced_line_amount": f"{billed_amt:.2f}",
                        "currency": "USD",
                    }
                )
                net = billed_amt
                if spec["scenario"] == "trap_billing_adjustment" and billed_amt != exp_amt:
                    diff = exp_amt - billed_amt
                    adjustments.append(
                        {
                            "adjustment_id": f"ADJ-{adj_no:04d}",
                            "invoice_line_id": line_id,
                            "adjustment_type": "debit_note" if diff > 0 else "credit_note",
                            "amount": f"{abs(diff):.2f}",
                            "adjustment_date": (d + timedelta(days=20)).isoformat(),
                            "reason": "Price correction to contract rate",
                        }
                    )
                    adj_no += 1
                    net = exp_amt
                under = max(exp_amt - net, Decimal("0"))
                over = max(net - exp_amt, Decimal("0"))
                truth.append(
                    {
                        "invoice_line_id": line_id,
                        "contract_id": spec["contract_id"],
                        "sku": s["sku"],
                        "invoice_date": d.isoformat(),
                        "scenario": spec["scenario"],
                        "expected_unit_price": f"{expected:.2f}",
                        "expected_line_amount": f"{exp_amt:.2f}",
                        "net_billed_amount": f"{net:.2f}",
                        "is_leakage": str(under > 0).lower(),
                        "seeded_leakage_amount": f"{under:.2f}",
                        "seeded_overbilling_amount": f"{over:.2f}",
                    }
                )
                line_no += 1
        scen_rows.append(
            {
                "contract_id": spec["contract_id"],
                "customer_name": spec["customer_name"],
                "industry": spec["industry"],
                "scenario": spec["scenario"],
                "escalation_type": spec["escalation"]["type"],
                "wording_variant": spec["wording_variant"],
                "format": spec["format"],
                "has_amendment": bool(spec["amendments"]),
                "has_side_letter": bool(spec["approved_discounts"]),
            }
        )

    write_csv(data_dir / "invoice_lines.csv", invoices)
    write_csv(data_dir / "billing_adjustments.csv", adjustments, fieldnames=ADJ_FIELDS)
    write_csv(
        data_dir / "customers.csv",
        [
            {
                "customer_id": s["customer_id"],
                "customer_name": s["customer_name"],
                "industry": s["industry"],
            }
            for s in specs
        ],
    )
    write_csv(
        data_dir / "reference" / "cpi_annual_pct.csv",
        [{"year": y, "cpi_pct": f"{v}"} for y, v in sorted(CPI.items())],
    )
    write_csv(eval_dir / "ground_truth.csv", truth)
    write_csv(eval_dir / "expected_price_schedule.csv", schedule_rows)
    write_csv(eval_dir / "contract_scenarios.csv", scen_rows)

    billed_total = sum(Decimal(r["invoiced_line_amount"]) for r in invoices)
    leak_total = sum(Decimal(r["seeded_leakage_amount"]) for r in truth)
    summary = {
        "contracts": len(specs),
        "invoice_lines": len(invoices),
        "adjustments": len(adjustments),
        "billed_total": f"{billed_total:,.2f}",
        "seeded_leakage": f"{leak_total:,.2f}",
        "leakage_pct_of_billed": f"{(leak_total / billed_total * 100):.2f}%",
        "leakage_lines": sum(r["is_leakage"] == "true" for r in truth),
    }
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=None, help="limit number of contracts")
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args()
    main(n_contracts=a.n, seed=a.seed)
