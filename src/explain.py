"""Finding explanations and rebilling review notes.

The LLM writes the language. Every number in its output must already exist in the finding's
facts (numeric guardrail); otherwise the deterministic template is used instead.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel

from src.findings import Finding
from src.schema import ContractTerms

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "explain_finding.v1.md"
PROMPT_VERSION = PROMPT_PATH.stem
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")

CAUSE_TEXT = {
    "MISSED_ESCALATION": "the contractual annual price escalation was never applied in billing",
    "PARTIAL_ESCALATION": "only some of the contractual anniversary escalations were applied in billing",
    "AMENDMENT_NOT_APPLIED": "a signed amendment changed the Unit Price but billing kept the old price",
    "PRICE_BELOW_CONTRACT": "the billed Unit Price is below the contracted price",
    "UNSUPPORTED_CREDIT": "the Unit Price was billed correctly, but credit notes without a matching approval reduced the net amount below the contract value",
    "OVERBILLING": "the billed Unit Price is above the contracted price",
}


class Explanation(BaseModel):
    headline: str
    narrative: str
    rebill_note_subject: str
    rebill_note_body: str


def facts(f: Finding) -> dict:
    return {
        "finding_id": f.finding_id,
        "customer": f.customer_name,
        "contract_id": f.contract_id,
        "sku": f.sku,
        "root_cause": f.root_cause,
        "root_cause_meaning": CAUSE_TEXT[f.root_cause],
        "invoice_lines_affected": f.line_count,
        "period": f"{f.first_date} to {f.last_date}",
        "amount_usd": f"{f.amount:,.2f}",
        "estimated_recoverable_usd": f"{f.recoverable_estimate:,.2f}",
        "latest_expected_unit_price_usd": f.expected_unit_price_latest,
        "latest_billed_unit_price_usd": f.billed_unit_price_latest,
        "contract_calculation": f.calculation_latest,
        "suggested_owner": f.owner,
        "recommended_action": f.recommended_action,
        "evidence": {
            k: {"clause_id": v["clause_id"], "page": v["page"], "quote": v["quote"]}
            for k, v in f.evidence.items()
        },
    }


def _norm(tok: str) -> str:
    t = tok.replace(",", "")
    if "." in t:
        t = t.rstrip("0").rstrip(".")
    return t.lstrip("0") or "0"


def allowed_numbers(fx: dict) -> set[str]:
    return {_norm(t) for t in NUM.findall(json.dumps(fx, default=str))} | {"1"}


def guardrail(exp: Explanation, fx: dict) -> list[str]:
    allowed = allowed_numbers(fx)
    text = " ".join(exp.model_dump().values())
    return sorted({t for t in (_norm(x) for x in NUM.findall(text)) if t not in allowed})


def template(f: Finding) -> Explanation:
    fx = facts(f)
    clauses = ", ".join(f"{k} clause {v['clause_id']}" for k, v in f.evidence.items())
    verb = "over-billed" if f.root_cause == "OVERBILLING" else "under-billed"
    headline = f"{f.customer_name}: {f.sku} {verb} by USD {fx['amount_usd']}"
    narrative = (
        f"{f.customer_name} ({f.contract_id}) was billed USD {f.billed_unit_price_latest} per unit for {f.sku} "
        f"on {f.line_count} invoice lines from {f.first_date} to {f.last_date}, while the contract requires "
        f"USD {f.expected_unit_price_latest} ({f.calculation_latest}). Likely cause: {CAUSE_TEXT[f.root_cause]}. "
        f"Potential amount: USD {fx['amount_usd']}; illustrative recoverable estimate: USD {fx['estimated_recoverable_usd']}. "
        f"Evidence: {clauses}."
    )
    body = (
        f"To: {f.owner}\n"
        f"Finding {f.finding_id} - {f.contract_id} / {f.sku}\n\n"
        f"Please review the {f.line_count} invoice lines billed between {f.first_date} and {f.last_date}. "
        f"Contract terms ({clauses}) give an expected Unit Price of USD {f.expected_unit_price_latest}; "
        f"billing used USD {f.billed_unit_price_latest}. Potential {verb.replace('-billed', 'billing')}: USD {fx['amount_usd']}.\n\n"
        f"Recommended action: {f.recommended_action}\n\n"
        "This note is for internal review only. No customer communication until approved."
    )
    return Explanation(
        headline=headline,
        narrative=narrative,
        rebill_note_subject=f"Rebilling review: {f.contract_id} {f.sku} - USD {fx['amount_usd']}",
        rebill_note_body=body,
    )


def explain(f: Finding, llm=None) -> tuple[Explanation, str, str]:
    """Return (explanation, source, guardrail_note)."""
    if llm is None:
        return template(f), "template", "LLM not used"
    fx = facts(f)
    prompt = PROMPT_PATH.read_text(encoding="utf-8").format(
        facts=json.dumps(fx, indent=2, default=str)
    )
    try:
        exp = Explanation.model_validate(
            llm.generate_json(prompt, schema=Explanation, prompt_version=PROMPT_VERSION)
        )
    except Exception as exc:  # network, quota, cache miss, bad JSON
        return template(f), "template", f"LLM unavailable: {type(exc).__name__}"
    bad = guardrail(exp, fx)
    if bad:
        return template(f), "template", f"Guardrail blocked LLM text: unmatched numbers {bad}"
    return exp, "llm", "All numbers verified against finding facts"


def explain_findings(
    findings: list[Finding],
    terms: dict[str, ContractTerms] | None = None,
    llm=None,
    use_llm: bool = True,
) -> None:
    if use_llm and llm is None:
        try:
            from src.llm.client import get_client

            llm = get_client()
        except Exception:
            llm = None
    for f in findings:
        exp, source, note = explain(f, llm)
        f.headline, f.narrative = exp.headline, exp.narrative
        f.rebill_note = f"{exp.rebill_note_subject}\n\n{exp.rebill_note_body}"
        f.explanation_source, f.guardrail_note = source, note
