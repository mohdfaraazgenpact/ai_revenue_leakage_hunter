"""Score pipeline output against seeded ground truth and write reports/evaluation_<label>.md.

    python -m src.evaluate                 # evaluates data/output/*
    python -m src.evaluate --check         # exit 1 if below acceptance thresholds (eval gate)

Ground truth is used for evaluation only and never as a detector feature.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
THRESHOLDS = {
    "line_recall": 0.90,
    "line_precision": 0.80,
    "dollar_error_pct": 5.0,
    "trap_false_positive_lines": 0,
}
EXPECTED_CAUSE = {
    "missed_escalation": "MISSED_ESCALATION",
    "partial_escalation": "PARTIAL_ESCALATION",
    "amendment_not_applied": "AMENDMENT_NOT_APPLIED",
    "price_below_contract": "PRICE_BELOW_CONTRACT",
}


def _dec(s) -> Decimal:
    return sum((Decimal(str(x)) for x in pd.Series(s).fillna("0")), Decimal("0"))


def evaluate(out_dir: Path = DATA / "output", eval_dir: Path = DATA / "eval") -> dict:
    lines = pd.read_csv(out_dir / "line_results.csv", dtype=str)
    truth = pd.read_csv(eval_dir / "ground_truth.csv", dtype=str)
    m = truth.merge(
        lines[["invoice_line_id", "status", "potential_underbilling", "potential_overbilling"]],
        on="invoice_line_id",
        how="left",
    )
    pred = m["status"].eq("POTENTIAL_UNDERBILLING")
    actual = m["is_leakage"].eq("true")
    tp, fp, fn = (
        int((pred & actual).sum()),
        int((pred & ~actual).sum()),
        int((~pred & actual).sum()),
    )
    detected, seeded = _dec(m["potential_underbilling"]), _dec(m["seeded_leakage_amount"])
    traps = m["scenario"].str.startswith(("trap_", "control"))
    per_scen = (
        m.assign(
            flagged=pred,
            seeded_flag=actual,
            det=m["potential_underbilling"].fillna("0").astype(float),
            seed=m["seeded_leakage_amount"].astype(float),
        )
        .groupby("scenario")
        .agg(
            lines=("flagged", "size"),
            seeded_lines=("seeded_flag", "sum"),
            flagged_lines=("flagged", "sum"),
            seeded_usd=("seed", "sum"),
            detected_usd=("det", "sum"),
        )
        .round(2)
        .reset_index()
    )
    res = {
        "lines": len(m),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "line_precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
        "line_recall": round(tp / (tp + fn), 4) if tp + fn else 0.0,
        "detected_usd": f"{detected:.2f}",
        "seeded_usd": f"{seeded:.2f}",
        "dollar_error_pct": round(float(abs(detected - seeded) / seeded * 100), 3)
        if seeded
        else 0.0,
        "trap_false_positive_lines": int((pred & traps).sum()),
        "review_lines": int(m["status"].eq("REVIEW").sum()),
        "overbilling_detected_usd": f"{_dec(m['potential_overbilling']):.2f}",
        "overbilling_seeded_usd": f"{_dec(m['seeded_overbilling_amount']):.2f}",
    }
    # contract-level and root-cause accuracy from findings
    fpath = out_dir / "findings.csv"
    scen = pd.read_csv(eval_dir / "contract_scenarios.csv", dtype=str)
    leak_contracts = set(truth.loc[truth["is_leakage"].eq("true"), "contract_id"])
    if fpath.exists() and fpath.stat().st_size > 1:
        f = pd.read_csv(fpath, dtype=str)
        f = f[f["root_cause"] != "OVERBILLING"]
        found = set(f["contract_id"])
        res["contract_precision"] = (
            round(len(found & leak_contracts) / len(found), 4) if found else 0.0
        )
        res["contract_recall"] = (
            round(len(found & leak_contracts) / len(leak_contracts), 4) if leak_contracts else 0.0
        )
        joined = f.merge(scen[["contract_id", "scenario"]], on="contract_id")
        joined = joined[joined["scenario"].isin(EXPECTED_CAUSE)]
        ok = (joined["root_cause"] == joined["scenario"].map(EXPECTED_CAUSE)).sum()
        res["root_cause_accuracy"] = round(ok / len(joined), 4) if len(joined) else 0.0
        res["findings"] = len(f)
    res["per_scenario"] = per_scen.to_dict(orient="records")
    return res


def check(res: dict) -> list[str]:
    fails = []
    if res["line_recall"] < THRESHOLDS["line_recall"]:
        fails.append(f"recall {res['line_recall']} < {THRESHOLDS['line_recall']}")
    if res["line_precision"] < THRESHOLDS["line_precision"]:
        fails.append(f"precision {res['line_precision']} < {THRESHOLDS['line_precision']}")
    if res["dollar_error_pct"] > THRESHOLDS["dollar_error_pct"]:
        fails.append(f"$ error {res['dollar_error_pct']}% > {THRESHOLDS['dollar_error_pct']}%")
    seeded_over = Decimal(res["overbilling_seeded_usd"])
    false_over = Decimal(res["overbilling_detected_usd"]) - seeded_over
    if false_over > seeded_over * Decimal("0.05") + 1:
        fails.append(f"USD {false_over:,.2f} of false overbilling (contract terms misread)")
    if res["trap_false_positive_lines"] > THRESHOLDS["trap_false_positive_lines"]:
        fails.append(f"{res['trap_false_positive_lines']} false-positive lines on traps/controls")
    return fails


def write_report(res: dict, label: str, terms_source: str) -> Path:
    REPORTS.mkdir(exist_ok=True)
    fails = check(res)
    md = [
        f"# Detection Evaluation - {label}",
        "",
        f"_Generated {datetime.now():%Y-%m-%d %H:%M}. Terms source: `{terms_source}`. Synthetic data only._",
        "",
        f"**Gate: {'PASS' if not fails else 'FAIL - ' + '; '.join(fails)}**",
        "",
        "| Metric | Value | Target |",
        "|---|---|---|",
        f"| Line recall | {res['line_recall']:.1%} | >= 90% |",
        f"| Line precision | {res['line_precision']:.1%} | >= 80% |",
        f"| Detected vs seeded $ | {Decimal(res['detected_usd']):,.2f} vs {Decimal(res['seeded_usd']):,.2f} "
        f"({res['dollar_error_pct']}% error) | within 5% |",
        f"| False positives on traps/controls (lines) | {res['trap_false_positive_lines']} | 0 |",
        f"| Contract-level recall / precision | {res.get('contract_recall', 0):.1%} / "
        f"{res.get('contract_precision', 0):.1%} | - |",
        f"| Root-cause accuracy | {res.get('root_cause_accuracy', 0):.1%} | - |",
        f"| Lines routed to review | {res['review_lines']} | - |",
        f"| Overbilling detected vs seeded $ | {res['overbilling_detected_usd']} vs {res['overbilling_seeded_usd']} | reported separately |",
        "",
        "## By seeded scenario",
        "",
        pd.DataFrame(res["per_scenario"]).to_markdown(index=False)
        if _has_tabulate()
        else pd.DataFrame(res["per_scenario"]).to_string(index=False),
    ]
    path = REPORTS / f"evaluation_{label}.md"
    path.write_text("\n".join(md) + "\n", encoding="utf-8")
    (REPORTS / f"evaluation_{label}.json").write_text(
        json.dumps(
            {**res, "label": label, "terms_source": terms_source, "gate_failures": fails}, indent=2
        ),
        encoding="utf-8",
    )
    return path


def _has_tabulate() -> bool:
    try:
        import tabulate  # noqa: F401

        return True
    except ImportError:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="exit 1 if thresholds are not met")
    ap.add_argument("--label", default=None)
    a = ap.parse_args()
    summary_path = DATA / "output" / "summary.json"
    terms_source = (
        json.loads(summary_path.read_text())["terms_source"] if summary_path.exists() else "?"
    )
    label = a.label or Path(terms_source).name
    res = evaluate()
    path = write_report(res, label, terms_source)
    print(json.dumps({k: v for k, v in res.items() if k != "per_scenario"}, indent=2))
    print(f"Report: {path}")
    fails = check(res)
    if a.check and fails:
        print("EVAL GATE FAILED: " + "; ".join(fails))
        sys.exit(1)


if __name__ == "__main__":
    main()
