"""Score pipeline output against seeded ground truth and write reports/evaluation_<label>.md.

    python -m src.evaluate                 # evaluates data/output/*
    python -m src.evaluate --check         # exit 1 if below acceptance thresholds (eval gate)

Ground truth is used for evaluation only and never as a detector feature.

Integrity rules: ground-truth IDs must be unique; prediction rows with status DUPLICATE (explicit
exact copies) are excluded and counted; any other repeated prediction ID makes the evaluation fail
(AmbiguousKeys). Unmatched records on either side are reported and fail the gate.

Metric families (kept separate on purpose):
- underbilling: line precision/recall (with TP/FP/FN/TN), aggregate and line-level $ error
- overbilling: its own line precision/recall and false-overbilling $
- outcome routing: engine status vs ``expected_outcome`` (MATCH / UNDERBILLING / OVERBILLING /
  REVIEW); lines routed to REVIEW are never counted as matches
- contract level: contract precision/recall and root-cause accuracy from findings
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
    "unmatched_records": 0,
}
EXPECTED_CAUSE = {
    "missed_escalation": "MISSED_ESCALATION",
    "partial_escalation": "PARTIAL_ESCALATION",
    "amendment_not_applied": "AMENDMENT_NOT_APPLIED",
    "price_below_contract": "PRICE_BELOW_CONTRACT",
}
STATUS_OUTCOME = {
    "MATCH": "MATCH",
    "POTENTIAL_UNDERBILLING": "UNDERBILLING",
    "POTENTIAL_OVERBILLING": "OVERBILLING",
    "REVIEW": "REVIEW",
}


class AmbiguousKeys(ValueError):
    pass


def _d(x) -> Decimal:
    s = "" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x).strip()
    return Decimal(s) if s else Decimal("0")


def _dec(s) -> Decimal:
    return sum((_d(x) for x in pd.Series(s)), Decimal("0"))


def _rate(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def _expected_outcome(truth: pd.DataFrame) -> pd.Series:
    if "expected_outcome" in truth:
        return truth["expected_outcome"]
    return pd.Series(
        [
            "UNDERBILLING" if leak == "true" else "OVERBILLING" if _d(over) > 0 else "MATCH"
            for leak, over in zip(
                truth["is_leakage"], truth["seeded_overbilling_amount"], strict=True
            )
        ],
        index=truth.index,
    )


def join_predictions(lines: pd.DataFrame, truth: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """One row per ground-truth line with its prediction. Raises AmbiguousKeys on repeated IDs."""
    dup_truth = truth["invoice_line_id"][truth["invoice_line_id"].duplicated()].unique()
    if len(dup_truth):
        raise AmbiguousKeys(f"ground truth repeats invoice_line_id: {list(dup_truth)[:10]}")
    excluded = int(lines["status"].eq("DUPLICATE").sum()) if "status" in lines else 0
    preds = lines[lines["status"].ne("DUPLICATE")] if "status" in lines else lines
    dup_pred = preds["invoice_line_id"][preds["invoice_line_id"].duplicated()].unique()
    if len(dup_pred):
        raise AmbiguousKeys(
            f"predictions repeat invoice_line_id (not marked DUPLICATE): {list(dup_pred)[:10]}"
        )
    cols = ["invoice_line_id", "status", "issue_type", "potential_underbilling"]
    cols += ["potential_overbilling"]
    preds = preds.reindex(columns=cols)
    m = truth.merge(preds, on="invoice_line_id", how="left", validate="one_to_one")
    integrity = {
        "exact_duplicate_rows_excluded": excluded,
        "unmatched_truth_lines": int(m["status"].isna().sum()),
        "unmatched_prediction_lines": int(
            (~preds["invoice_line_id"].isin(truth["invoice_line_id"])).sum()
        ),
    }
    return m, integrity


def evaluate(out_dir: Path = DATA / "output", eval_dir: Path = DATA / "eval") -> dict:
    lines = pd.read_csv(out_dir / "line_results.csv", dtype=str, keep_default_na=False)
    truth = pd.read_csv(eval_dir / "ground_truth.csv", dtype=str, keep_default_na=False)
    m, integrity = join_predictions(lines, truth)
    m["expected_outcome"] = _expected_outcome(m)
    m["outcome"] = m["status"].map(STATUS_OUTCOME).fillna("MISSING")

    pred = m["status"].eq("POTENTIAL_UNDERBILLING")
    actual = m["is_leakage"].eq("true")
    tp, fp, fn, tn = (
        int((pred & actual).sum()),
        int((pred & ~actual).sum()),
        int((~pred & actual).sum()),
        int((~pred & ~actual).sum()),
    )
    det_line = m["potential_underbilling"].map(_d)
    seed_line = m["seeded_leakage_amount"].map(_d)
    detected, seeded = sum(det_line, Decimal("0")), sum(seed_line, Decimal("0"))
    abs_err = (det_line - seed_line).abs()
    tp_err = abs_err[pred & actual]

    pred_o = m["status"].eq("POTENTIAL_OVERBILLING")
    over_det = m["potential_overbilling"].map(_d)
    act_o = m["seeded_overbilling_amount"].map(_d) > 0
    o_tp, o_fp, o_fn = (
        int((pred_o & act_o).sum()),
        int((pred_o & ~act_o).sum()),
        int((~pred_o & act_o).sum()),
    )
    false_over = sum(over_det[~act_o], Decimal("0"))

    traps = m["scenario"].str.startswith(("trap_", "control"))
    exp_review = m["expected_outcome"].eq("REVIEW")
    per_scen = (
        m.assign(
            flagged=pred,
            seeded_flag=actual,
            review=m["status"].eq("REVIEW"),
            det=det_line.astype(float),
            seed=seed_line.astype(float),
        )
        .groupby("scenario")
        .agg(
            lines=("flagged", "size"),
            seeded_lines=("seeded_flag", "sum"),
            flagged_lines=("flagged", "sum"),
            review_lines=("review", "sum"),
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
        "tn": tn,
        "line_precision": _rate(tp, tp + fp),
        "line_recall": _rate(tp, tp + fn),
        "detected_usd": f"{detected:.2f}",
        "seeded_usd": f"{seeded:.2f}",
        "dollar_error_pct": round(float(abs(detected - seeded) / seeded * 100), 3)
        if seeded
        else 0.0,
        "line_abs_error_mean_usd": f"{(sum(abs_err, Decimal('0')) / len(m)):.2f}"
        if len(m)
        else "0.00",
        "line_abs_error_max_usd": f"{max(abs_err, default=Decimal('0')):.2f}",
        "lines_with_amount_error": int((abs_err > Decimal("0.01")).sum()),
        "flagged_leakage_lines_with_wrong_amount": int((tp_err > Decimal("0.01")).sum()),
        "trap_false_positive_lines": int((pred & traps).sum()),
        "review_lines": int(m["status"].eq("REVIEW").sum()),
        "review_lines_on_seeded_leakage": int((m["status"].eq("REVIEW") & actual).sum()),
        "review_by_issue": m.loc[m["status"].eq("REVIEW"), "issue_type"]
        .value_counts()
        .sort_index()
        .to_dict(),
        "expected_review_lines": int(exp_review.sum()),
        "expected_review_routed": int((exp_review & m["status"].eq("REVIEW")).sum()),
        "outcome_accuracy": _rate(int(m["outcome"].eq(m["expected_outcome"]).sum()), len(m)),
        "overbilling_tp": o_tp,
        "overbilling_fp": o_fp,
        "overbilling_fn": o_fn,
        "overbilling_precision": _rate(o_tp, o_tp + o_fp),
        "overbilling_recall": _rate(o_tp, o_tp + o_fn),
        "overbilling_detected_usd": f"{sum(over_det, Decimal('0')):.2f}",
        "overbilling_seeded_usd": f"{_dec(m['seeded_overbilling_amount']):.2f}",
        "false_overbilling_usd": f"{false_over:.2f}",
        **integrity,
        "unmatched_records": integrity["unmatched_truth_lines"]
        + integrity["unmatched_prediction_lines"],
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
    false_over = Decimal(res["false_overbilling_usd"])
    if false_over > seeded_over * Decimal("0.05") + 1:
        fails.append(f"USD {false_over:,.2f} of false overbilling (contract terms misread)")
    if res["trap_false_positive_lines"] > THRESHOLDS["trap_false_positive_lines"]:
        fails.append(f"{res['trap_false_positive_lines']} false-positive lines on traps/controls")
    if res["unmatched_records"] > THRESHOLDS["unmatched_records"]:
        fails.append(
            f"{res['unmatched_records']} unmatched records ({res['unmatched_truth_lines']} truth, "
            f"{res['unmatched_prediction_lines']} predictions)"
        )
    if res["expected_review_routed"] < res["expected_review_lines"]:
        fails.append(
            f"only {res['expected_review_routed']}/{res['expected_review_lines']} lines that must "
            "go to REVIEW were routed there"
        )
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
        "## Underbilling (revenue leakage)",
        "",
        "| Metric | Value | Target |",
        "|---|---|---|",
        f"| Line recall | {res['line_recall']:.1%} ({res['tp']}/{res['tp'] + res['fn']}) | >= 90% |",
        f"| Line precision | {res['line_precision']:.1%} ({res['tp']}/{res['tp'] + res['fp']}) | >= 80% |",
        f"| Confusion (n={res['lines']}) | TP {res['tp']} · FP {res['fp']} · FN {res['fn']} · "
        f"TN {res['tn']} | - |",
        f"| Detected vs seeded $ | {Decimal(res['detected_usd']):,.2f} vs {Decimal(res['seeded_usd']):,.2f} "
        f"({res['dollar_error_pct']}% error) | within 5% |",
        f"| Line-level abs. $ error (mean / max) | {res['line_abs_error_mean_usd']} / "
        f"{res['line_abs_error_max_usd']} ({res['lines_with_amount_error']} lines off by > 1c) | - |",
        f"| Flagged leakage lines with the wrong amount | "
        f"{res['flagged_leakage_lines_with_wrong_amount']} | 0 |",
        f"| False positives on traps/controls (lines) | {res['trap_false_positive_lines']} | 0 |",
        f"| Contract-level recall / precision | {res.get('contract_recall', 0):.1%} / "
        f"{res.get('contract_precision', 0):.1%} | - |",
        f"| Root-cause accuracy | {res.get('root_cause_accuracy', 0):.1%} | - |",
        "",
        "## Overbilling (separate problem, never netted)",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Line recall / precision | {res['overbilling_recall']:.1%} / "
        f"{res['overbilling_precision']:.1%} (TP {res['overbilling_tp']} · FP {res['overbilling_fp']} "
        f"· FN {res['overbilling_fn']}) |",
        f"| Detected vs seeded $ | {res['overbilling_detected_usd']} vs {res['overbilling_seeded_usd']} |",
        f"| False overbilling $ | {res['false_overbilling_usd']} |",
        "",
        "## Review routing and data integrity",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Outcome accuracy (MATCH / UNDER / OVER / REVIEW) | {res['outcome_accuracy']:.1%} |",
        f"| Lines that must go to REVIEW, routed there | {res['expected_review_routed']} / "
        f"{res['expected_review_lines']} |",
        f"| Lines routed to REVIEW (all) | {res['review_lines']} "
        f"({res['review_lines_on_seeded_leakage']} on seeded leakage, counted as missed) |",
        f"| REVIEW by issue type | {res['review_by_issue'] or '-'} |",
        f"| Exact duplicate rows excluded | {res['exact_duplicate_rows_excluded']} |",
        f"| Unmatched truth / prediction lines | {res['unmatched_truth_lines']} / "
        f"{res['unmatched_prediction_lines']} |",
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
