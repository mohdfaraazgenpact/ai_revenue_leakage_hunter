"""Field-level extraction accuracy against gold terms, per extractor and per wording variant.

python -m src.evaluate_extraction        # evaluates every data/extracted/<name>/ present
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

from src.extract.document_loader import normalize
from src.schema import ContractTerms

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REPORTS = ROOT / "reports"


def _load(d: Path) -> dict[str, ContractTerms]:
    return {
        p.stem: ContractTerms.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(d.glob("*.json"))
    }


def compare(gold: ContractTerms, pred: ContractTerms | None) -> list[dict]:
    """One row per key field: group, field, gold, predicted, correct, citation_verified."""
    rows = []

    def canon(v):
        if isinstance(v, Decimal):
            return format(v.normalize(), "f")
        if isinstance(v, tuple):
            return tuple(canon(x) for x in v)
        return v

    def add(group, field, g, p, verified=None):
        g, p = canon(g), canon(p)
        rows.append(
            {
                "contract_id": gold.contract_id,
                "group": group,
                "field": field,
                "gold": str(g),
                "pred": str(p),
                "correct": str(g) == str(p),
                "verified": verified,
            }
        )

    if pred is None:
        pred = ContractTerms(
            contract_id=gold.contract_id,
            customer_name="",
            effective_date="1900-01-01",
            end_date="1900-01-01",
            prices=[],
        )
    add(
        "customer_and_dates",
        "customer_name",
        normalize(gold.customer_name),
        normalize(pred.customer_name),
    )
    add("customer_and_dates", "effective_date", gold.effective_date, pred.effective_date)
    add("customer_and_dates", "end_date", gold.end_date, pred.end_date)
    for gp in gold.prices:
        pp = pred.price_for(gp.sku)
        add(
            "prices",
            f"price:{gp.sku}",
            gp.unit_price,
            pp.unit_price if pp else None,
            pp.citation.verified if pp and pp.citation else None,
        )
    ge, pe = gold.escalation, pred.escalation
    ver = pe.citation.verified if pe.citation else None
    add("escalation", "escalation.type", ge.type, pe.type, ver)
    if ge.type == "fixed_pct":
        add(
            "escalation",
            "escalation.rate_pct",
            ge.rate_pct.normalize(),
            pe.rate_pct.normalize() if pe.rate_pct is not None else None,
            ver,
        )
    if ge.type == "cpi":
        add(
            "escalation",
            "escalation.floor_pct",
            ge.floor_pct.normalize(),
            pe.floor_pct.normalize() if pe.floor_pct is not None else None,
            ver,
        )
        add(
            "escalation",
            "escalation.cap_pct",
            ge.cap_pct.normalize(),
            pe.cap_pct.normalize() if pe.cap_pct is not None else None,
            ver,
        )
    if ge.type != "none":
        add(
            "escalation",
            "escalation.first_escalation_date",
            ge.first_escalation_date,
            pe.first_escalation_date,
            ver,
        )
    for ga in gold.amendments:
        pa = next(
            (
                a
                for a in pred.amendments
                if a.sku == ga.sku and a.effective_date == ga.effective_date
            ),
            None,
        )
        add(
            "amendments",
            f"amendment:{ga.sku}",
            (ga.effective_date, ga.new_unit_price),
            (pa.effective_date, pa.new_unit_price) if pa else None,
            pa.citation.verified if pa and pa.citation else None,
        )
    for gd in gold.approved_discounts:
        pd_ = next((d for d in pred.approved_discounts if d.sku == gd.sku), None)
        add(
            "discounts",
            f"discount:{gd.sku}",
            (gd.start_date, gd.end_date, gd.discount_pct.normalize()),
            (pd_.start_date, pd_.end_date, pd_.discount_pct.normalize()) if pd_ else None,
            pd_.citation.verified if pd_ and pd_.citation else None,
        )
    # spurious extra amendments/discounts count as errors
    extra = (
        len(pred.amendments)
        - len(gold.amendments)
        + len(pred.approved_discounts)
        - len(gold.approved_discounts)
    )
    for i in range(max(extra, 0)):
        add("spurious", f"extra_item_{i}", None, "extra")
    return rows


def evaluate(name: str) -> tuple[pd.DataFrame, dict]:
    gold = _load(DATA / "eval" / "gold")
    pred = _load(DATA / "extracted" / name)
    scen = pd.read_csv(DATA / "eval" / "contract_scenarios.csv", dtype=str)
    rows = [r for cid, g in gold.items() for r in compare(g, pred.get(cid))]
    df = pd.DataFrame(rows).merge(
        scen[["contract_id", "escalation_type", "wording_variant"]], on="contract_id"
    )
    key = df[df["group"] != "spurious"]
    summary = {
        "extractor": name,
        "contracts_extracted": len(pred),
        "contracts_total": len(gold),
        "key_field_accuracy": round(key["correct"].mean(), 4),
        "fields": int(len(key)),
        "spurious_items": int((df["group"] == "spurious").sum()),
        "by_group": key.groupby("group")["correct"].mean().round(4).to_dict(),
        "escalation_by_wording": df[df["group"] == "escalation"]
        .assign(variant=lambda x: x["escalation_type"] + "/v" + x["wording_variant"])
        .groupby("contract_id")
        .agg(variant=("variant", "first"), ok=("correct", "all"))
        .groupby("variant")["ok"]
        .agg(["sum", "count"])
        .apply(lambda r: f"{r['sum']}/{r['count']}", axis=1)
        .to_dict(),
        "contracts_all_correct": int(key.groupby("contract_id")["correct"].all().sum()),
    }
    verified = df["verified"].dropna()
    summary["citations_verified_pct"] = (
        round(float(verified.astype(bool).mean()), 4) if len(verified) else None
    )
    return df, summary


def main():
    REPORTS.mkdir(exist_ok=True)
    names = [
        p.name
        for p in sorted((DATA / "extracted").glob("*"))
        if p.is_dir() and any(p.glob("*.json"))
    ]
    if not names:
        print(
            "No extracted terms found. Run: python -m src.extract.run_extraction --extractor both"
        )
        return
    summaries = []
    for n in names:
        df, s = evaluate(n)
        df.to_csv(REPORTS / f"extraction_fields_{n}.csv", index=False)
        summaries.append(s)
        print(json.dumps(s, indent=2, default=str))
    (REPORTS / "extraction_summary.json").write_text(
        json.dumps(summaries, indent=2, default=str), encoding="utf-8"
    )
    md = [
        f"# Extraction Accuracy vs Gold ({datetime.now():%Y-%m-%d %H:%M})",
        "",
        "_Synthetic contracts only._",
        "",
        "| Extractor | Key-field accuracy | Contracts fully correct | Citations verified | Spurious items |",
        "|---|---|---|---|---|",
    ]
    for s in summaries:
        cv = "-" if s["citations_verified_pct"] is None else f"{s['citations_verified_pct']:.0%}"
        md.append(
            f"| {s['extractor']} | {s['key_field_accuracy']:.1%} | {s['contracts_all_correct']}/{s['contracts_total']} "
            f"| {cv} | {s['spurious_items']} |"
        )
    md += [
        "",
        "## Escalation clause correct, by wording variant",
        "",
        "| Variant | " + " | ".join(s["extractor"] for s in summaries) + " |",
        "|---|" + "---|" * len(summaries),
    ]
    variants = sorted({v for s in summaries for v in s["escalation_by_wording"]})
    for v in variants:
        md.append(
            f"| {v} | "
            + " | ".join(s["escalation_by_wording"].get(v, "-") for s in summaries)
            + " |"
        )
    md += [
        "",
        "## Accuracy by field group",
        "",
        "| Group | " + " | ".join(s["extractor"] for s in summaries) + " |",
        "|---|" + "---|" * len(summaries),
    ]
    for g in sorted({g for s in summaries for g in s["by_group"]}):
        md.append(
            f"| {g} | " + " | ".join(f"{s['by_group'].get(g, 0):.0%}" for s in summaries) + " |"
        )
    (REPORTS / "extraction_comparison.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"Report: {REPORTS / 'extraction_comparison.md'}")


if __name__ == "__main__":
    main()
