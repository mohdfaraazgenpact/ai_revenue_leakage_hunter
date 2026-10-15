"""Evaluation integrity: ambiguous keys fail, unmatched records are reported, metrics stay separate."""

import pandas as pd
import pytest

from src.evaluate import AmbiguousKeys, check, evaluate, join_predictions


def _truth(*rows):
    cols = [
        "invoice_line_id",
        "contract_id",
        "scenario",
        "is_leakage",
        "seeded_leakage_amount",
        "seeded_overbilling_amount",
        "expected_outcome",
    ]
    return pd.DataFrame(rows, columns=cols)


def _pred(*rows):
    cols = ["invoice_line_id", "status", "issue_type", "potential_underbilling"]
    return pd.DataFrame(rows, columns=[*cols, "potential_overbilling"])


T = _truth(
    ("L1", "C", "missed_escalation", "true", "50.00", "0.00", "UNDERBILLING"),
    ("L2", "C", "control", "false", "0.00", "0.00", "MATCH"),
    ("L3", "C", "overbilling", "false", "0.00", "20.00", "OVERBILLING"),
    ("L4", "C", "invalid_input", "false", "0.00", "0.00", "REVIEW"),
)
P = _pred(
    ("L1", "POTENTIAL_UNDERBILLING", "", "50.00", "0.00"),
    ("L2", "MATCH", "", "0.00", "0.00"),
    ("L3", "POTENTIAL_OVERBILLING", "", "0.00", "20.00"),
    ("L4", "REVIEW", "INVALID_INPUT", "", ""),
)


def _eval(tmp_path, truth, pred):
    (tmp_path / "out").mkdir()
    pred.to_csv(tmp_path / "out" / "line_results.csv", index=False)
    truth.to_csv(tmp_path / "ground_truth.csv", index=False)
    pd.DataFrame(columns=["contract_id", "scenario"]).to_csv(
        tmp_path / "contract_scenarios.csv", index=False
    )
    return evaluate(out_dir=tmp_path / "out", eval_dir=tmp_path)


def test_clean_run_scores_perfectly_and_passes(tmp_path):
    res = _eval(tmp_path, T, P)
    assert (res["tp"], res["fp"], res["fn"], res["tn"]) == (1, 0, 0, 3)
    assert res["overbilling_recall"] == 1.0 and res["false_overbilling_usd"] == "0.00"
    assert res["outcome_accuracy"] == 1.0 and res["expected_review_routed"] == 1
    assert check(res) == []


def test_repeated_prediction_ids_fail_instead_of_multiplying_rows():
    with pytest.raises(AmbiguousKeys):
        join_predictions(pd.concat([P, P.iloc[[0]]]), T)


def test_repeated_truth_ids_fail():
    with pytest.raises(AmbiguousKeys):
        join_predictions(P, pd.concat([T, T.iloc[[0]]]))


def test_explicit_duplicate_rows_are_excluded_and_counted():
    dup = P.iloc[[0]].assign(status="DUPLICATE", issue_type="EXACT_DUPLICATE")
    m, integrity = join_predictions(pd.concat([P, dup]), T)
    assert len(m) == 4 and integrity["exact_duplicate_rows_excluded"] == 1


def test_unmatched_records_are_reported_and_fail_the_gate(tmp_path):
    pred = pd.concat([P.iloc[1:], _pred(("LX", "MATCH", "", "0.00", "0.00"))])
    res = _eval(tmp_path, T, pred)
    assert res["unmatched_truth_lines"] == 1 and res["unmatched_prediction_lines"] == 1
    assert any("unmatched" in f for f in check(res))


def test_review_on_a_leakage_line_is_a_miss_not_a_match(tmp_path):
    pred = P.copy()
    pred.loc[0, ["status", "potential_underbilling"]] = ["REVIEW", ""]
    res = _eval(tmp_path, T, pred)
    assert res["fn"] == 1 and res["review_lines_on_seeded_leakage"] == 1
    assert res["outcome_accuracy"] == 0.75


def test_missed_review_routing_fails_the_gate(tmp_path):
    pred = P.copy()
    pred.loc[3, ["status", "issue_type"]] = ["MATCH", ""]
    res = _eval(tmp_path, T, pred)
    assert any("REVIEW" in f for f in check(res))


def test_wrong_amount_on_a_correct_flag_is_reported(tmp_path):
    pred = P.copy()
    pred.loc[0, "potential_underbilling"] = "45.00"
    res = _eval(tmp_path, T, pred)
    assert res["tp"] == 1 and res["flagged_leakage_lines_with_wrong_amount"] == 1
