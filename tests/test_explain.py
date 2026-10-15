from decimal import Decimal

from src.explain import Explanation, explain, facts, guardrail
from src.findings import Finding
from src.llm.client import FakeLLMClient


def _finding():
    return Finding(
        finding_id="F-001",
        contract_id="C-2008",
        customer_id="CU-1",
        customer_name="Acme",
        sku="S1",
        root_cause="MISSED_ESCALATION",
        line_count=12,
        first_date="2025-01-15",
        last_date="2025-12-15",
        amount=Decimal("26123.00"),
        recoverability=Decimal("1"),
        recoverable_estimate=Decimal("26123.00"),
        extraction_confidence=0.95,
        priority_score=1.0,
        expected_unit_price_latest="105.00",
        billed_unit_price_latest="100.00",
        calculation_latest="USD 100.00 (base price) x (1 + 5%) [2025-01-01] = USD 105.00",
        owner="Pricing",
        recommended_action="Fix price master",
        invoice_line_ids=["L1"],
        evidence={"escalation": {"clause_id": "4.2", "page": 1, "quote": "increase by 5%"}},
    )


def _exp(narr):
    return {
        "headline": "Missed escalation for Acme",
        "narrative": narr,
        "rebill_note_subject": "Rebill review C-2008",
        "rebill_note_body": "See clause 4.2.",
    }


def test_guardrail_accepts_numbers_from_facts():
    f = _finding()
    e = Explanation(
        **_exp(
            "Acme was billed USD 100.00 instead of USD 105.00 on 12 lines; USD 26,123.00 potential."
        )
    )
    assert guardrail(e, facts(f)) == []


def test_guardrail_blocks_invented_numbers_and_falls_back_to_template():
    f = _finding()
    llm = FakeLLMClient([_exp("Acme owes USD 31,500.00 which is 7% of revenue.")])
    exp, source, note = explain(f, llm)
    assert source == "template"
    assert "31500" in note
    assert "26,123.00" in exp.narrative  # template uses engine numbers only


def test_llm_text_used_when_numbers_check_out():
    llm = FakeLLMClient([_exp("Billing kept USD 100.00 after the 5% escalation in clause 4.2.")])
    exp, source, _ = explain(_finding(), llm)
    assert source == "llm"
    assert "clause 4.2" in exp.narrative


def test_llm_failure_falls_back_to_template():
    llm = FakeLLMClient(["not json"])
    _, source, note = explain(_finding(), llm)
    assert source == "template"
    assert "unavailable" in note
