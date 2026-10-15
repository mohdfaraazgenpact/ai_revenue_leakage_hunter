"""Generate a small synthetic portfolio in a temp dir and run every stage offline."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from src.evaluate import check, evaluate
from src.evaluate_extraction import compare
from src.extract import llm_extractor, rule_extractor
from src.extract.document_loader import load_document, verify_quote
from src.generate_synthetic_data import main as generate
from src.llm.client import FakeLLMClient
from src.pipeline import run
from src.reconcile import load_terms


@pytest.fixture(scope="module")
def portfolio(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("data")
    generate(d, n_contracts=8)
    return d


def test_generator_outputs(portfolio):
    assert len(list((portfolio / "contracts").iterdir())) == 8
    assert len(list((portfolio / "eval" / "gold").glob("*.json"))) == 8
    gold = load_terms(portfolio / "eval" / "gold")
    for t in gold.values():  # every gold citation must be findable in its document
        pages = load_document(next((portfolio / "contracts").glob(f"{t.contract_id}.*")))
        for p in t.prices:
            assert verify_quote(p.citation.quote, pages)[0]


def test_pipeline_with_gold_terms_matches_ground_truth(portfolio, tmp_path):
    run(portfolio / "eval" / "gold", data_dir=portfolio, out_dir=tmp_path)
    res = evaluate(out_dir=tmp_path, eval_dir=portfolio / "eval")
    assert res["fn"] == 0 and res["fp"] == 0
    assert check(res) == [] or res["tp"] == 0  # gate passes (small samples may have no leakage)


def test_rule_extractor_reads_prices_and_dates(portfolio):
    gold = load_terms(portfolio / "eval" / "gold")
    for t in gold.values():
        path = next((portfolio / "contracts").glob(f"{t.contract_id}.*"))
        pred = rule_extractor.extract(path)
        rows = compare(t, pred)
        assert all(r["correct"] for r in rows if r["group"] in ("prices", "customer_and_dates")), (
            t.contract_id
        )


def _llm_answer_from_gold(t):
    """Build the JSON a perfect LLM would return, from gold terms."""

    def c(cit):
        return {"clause_id": cit.clause_id, "page": cit.page or 1, "quote": cit.quote}

    e = t.escalation
    return {
        "customer_name": t.customer_name,
        "effective_date": str(t.effective_date),
        "effective_date_citation": {"clause_id": "1.2", "page": 1, "quote": "Effective Date"},
        "end_date": str(t.end_date),
        "end_date_citation": {"clause_id": "2.1", "page": 1, "quote": "continues until"},
        "currency": "USD",
        "prices": [
            {
                "sku": p.sku,
                "description": p.description,
                "unit_price": float(p.unit_price),
                "citation": c(p.citation),
            }
            for p in t.prices
        ],
        "escalation": {
            "type": e.type,
            "rate_pct": float(e.rate_pct) if e.rate_pct else None,
            "floor_pct": float(e.floor_pct) if e.floor_pct else None,
            "cap_pct": float(e.cap_pct) if e.cap_pct else None,
            "first_escalation_date": str(e.first_escalation_date)
            if e.first_escalation_date
            else None,
            "derivation": "test",
            "citation": c(e.citation),
        },
        "amendments": [
            {
                "amendment_id": a.amendment_id,
                "effective_date": str(a.effective_date),
                "sku": a.sku,
                "new_unit_price": float(a.new_unit_price),
                "citation": c(a.citation),
            }
            for a in t.amendments
        ],
        "approved_discounts": [
            {
                "sku": d.sku,
                "discount_pct": float(d.discount_pct),
                "start_date": str(d.start_date),
                "end_date": str(d.end_date),
                "citation": c(d.citation),
            }
            for d in t.approved_discounts
        ],
        "confidence": {
            "customer_and_dates": 0.95,
            "prices": 0.95,
            "escalation": 0.9,
            "amendments": 0.9,
            "discounts": 0.9,
        },
    }


def test_llm_extractor_with_perfect_answers_is_fully_correct_and_verified(portfolio):
    gold = load_terms(portfolio / "eval" / "gold")
    t = next(iter(gold.values()))
    path = next((portfolio / "contracts").glob(f"{t.contract_id}.*"))
    pred, issues = llm_extractor.extract(path, FakeLLMClient([_llm_answer_from_gold(t)]))
    assert issues == []
    assert all(r["correct"] for r in compare(t, pred))
    assert all(p.citation.verified for p in pred.prices)


def test_llm_hallucinated_quote_goes_to_review_and_lowers_confidence(portfolio):
    gold = load_terms(portfolio / "eval" / "gold")
    t = next(iter(gold.values()))
    path = next((portfolio / "contracts").glob(f"{t.contract_id}.*"))
    ans = _llm_answer_from_gold(t)
    ans["prices"][0]["citation"]["quote"] = "Unit price shall be USD 1.00 forever."
    ans["prices"][0]["unit_price"] = 1.0
    pred, issues = llm_extractor.extract(path, FakeLLMClient([json.dumps(ans)]))
    assert any(i["issue"] == "quote not found in document" for i in issues)
    assert pred.prices[0].citation.verified is False
    assert pred.field_confidence["prices"] <= 0.5
    assert pred.prices[0].unit_price == Decimal("1.00")
