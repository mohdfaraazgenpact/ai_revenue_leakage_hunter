"""Gemini contract-term extraction with verified citations and a review queue.

The LLM returns values plus verbatim quotes. Code then:
  1. validates types/dates via the canonical schema,
  2. verifies every quote exists in the document (on the cited page where possible),
  3. checks that numeric values appear in their supporting quote,
  4. lowers confidence and raises review items when any check fails.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, Field

from src.contract_docs import _WORDS
from src.extract.document_loader import Page, full_text, load_document, verify_quote
from src.llm.client import LLMClient
from src.schema import Amendment, ApprovedDiscount, Citation, ContractTerms, Escalation, SkuPrice

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "extract_terms.v2.md"
PROMPT_VERSION = PROMPT_PATH.stem


# ---- LLM-facing schema (simple types that Gemini structured output supports) ----
class LLMCitation(BaseModel):
    clause_id: str
    page: int
    quote: str


class LLMPrice(BaseModel):
    sku: str
    description: str
    unit_price: float
    citation: LLMCitation


class LLMEscalation(BaseModel):
    type: str = Field(description="none | fixed_pct | cpi")
    rate_pct: float | None = None
    floor_pct: float | None = None
    cap_pct: float | None = None
    first_escalation_date: str | None = Field(default=None, description="YYYY-MM-DD")
    compounding: bool | None = Field(
        default=None, description="true compounding, false simple, null if not stated"
    )
    derivation: str = Field(description="One sentence: how the rate and first date were determined")
    citation: LLMCitation | None = None


class LLMAmendment(BaseModel):
    amendment_id: str
    effective_date: str
    sku: str | None = None
    new_unit_price: float | None = None
    new_escalation_rate_pct: float | None = None
    citation: LLMCitation


class LLMDiscount(BaseModel):
    sku: str | None = None
    discount_pct: float
    start_date: str
    end_date: str
    citation: LLMCitation


class LLMConfidence(BaseModel):
    customer_and_dates: float
    prices: float
    escalation: float
    amendments: float
    discounts: float


class LLMContractTerms(BaseModel):
    customer_name: str
    effective_date: str
    effective_date_citation: LLMCitation
    end_date: str
    end_date_citation: LLMCitation
    currency: str
    prices: list[LLMPrice]
    escalation: LLMEscalation
    amendments: list[LLMAmendment]
    approved_discounts: list[LLMDiscount]
    confidence: LLMConfidence


# ---- verification helpers -------------------------------------------------------
def _dec(x) -> Decimal | None:
    return None if x is None else Decimal(str(round(float(x), 4))).normalize()


def _money(x) -> Decimal | None:
    return None if x is None else Decimal(str(round(float(x), 2))).quantize(Decimal("0.01"))


def _value_in_quote(value: Decimal | None, quote: str) -> bool:
    if value is None:
        return True
    q = quote.lower().replace(",", "")
    v = value.normalize()
    candidates = {format(v, "f"), f"{value:.2f}", f"{value:.1f}"}
    words = _WORDS.get(format(v, "f"))
    return any(c in q for c in candidates) or (words is not None and words in q)


class _Verifier:
    def __init__(self, pages: list[Page], contract_id: str):
        self.pages, self.contract_id = pages, contract_id
        self.issues: list[dict] = []

    def cite(self, c: LLMCitation | None, field: str, value=None) -> Citation | None:
        if c is None:
            return None
        ok, page = verify_quote(c.quote, self.pages, c.page)
        if not ok:
            self.issues.append(
                {
                    "contract_id": self.contract_id,
                    "field": field,
                    "issue": "quote not found in document",
                    "quote": c.quote,
                }
            )
        elif value is not None and not _value_in_quote(value, c.quote):
            self.issues.append(
                {
                    "contract_id": self.contract_id,
                    "field": field,
                    "issue": f"value {value} not present in quote",
                    "quote": c.quote,
                }
            )
            ok = False
        return Citation(clause_id=c.clause_id, page=page or c.page, quote=c.quote, verified=ok)

    def flagged(self, prefix: str) -> bool:
        return any(i["field"].startswith(prefix) for i in self.issues)


def _date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s.strip()[:10])
    except ValueError:
        return None


def build_prompt(contract_id: str, pages: list[Page]) -> str:
    return PROMPT_PATH.read_text(encoding="utf-8").format(
        contract_id=contract_id, document=full_text(pages)
    )


def extract(
    path: Path, llm: LLMClient, contract_id: str | None = None, pages: list[Page] | None = None
) -> tuple[ContractTerms, list[dict]]:
    pages = pages or load_document(path)
    contract_id = contract_id or Path(path).stem
    raw = llm.generate_json(
        build_prompt(contract_id, pages), schema=LLMContractTerms, prompt_version=PROMPT_VERSION
    )
    r = LLMContractTerms.model_validate(raw)
    v = _Verifier(pages, contract_id)

    prices = [
        SkuPrice(
            sku=p.sku.strip(),
            description=p.description,
            unit_price=_money(p.unit_price),
            citation=v.cite(p.citation, f"prices.{p.sku}", _dec(p.unit_price)),
        )
        for p in r.prices
    ]
    e = r.escalation
    etype = e.type.strip().lower() if e.type else "none"
    if etype not in ("none", "fixed_pct", "cpi"):
        v.issues.append(
            {
                "contract_id": contract_id,
                "field": "escalation.type",
                "issue": f"unknown type {e.type}",
                "quote": "",
            }
        )
        etype = "none"
    esc = Escalation(
        type=etype,
        rate_pct=_dec(e.rate_pct),
        floor_pct=_dec(e.floor_pct),
        cap_pct=_dec(e.cap_pct),
        first_escalation_date=_date(e.first_escalation_date),
        compounding=True if e.compounding is None else e.compounding,  # D-004 default
        citation=v.cite(
            e.citation, "escalation", _dec(e.rate_pct) if etype == "fixed_pct" else None
        ),
    )
    if etype != "none" and esc.first_escalation_date is None:
        v.issues.append(
            {
                "contract_id": contract_id,
                "field": "escalation.first_escalation_date",
                "issue": "escalation without a first escalation date",
                "quote": "",
            }
        )
    amendments = [
        Amendment(
            amendment_id=a.amendment_id,
            effective_date=_date(a.effective_date),
            sku=a.sku,
            new_unit_price=_money(a.new_unit_price),
            new_escalation_rate_pct=_dec(a.new_escalation_rate_pct),
            citation=v.cite(a.citation, f"amendments.{a.amendment_id}", _dec(a.new_unit_price)),
        )
        for a in r.amendments
    ]
    discounts = [
        ApprovedDiscount(
            sku=d.sku,
            discount_pct=_dec(d.discount_pct),
            start_date=_date(d.start_date),
            end_date=_date(d.end_date),
            citation=v.cite(d.citation, f"discounts.{d.sku}", _dec(d.discount_pct)),
        )
        for d in r.approved_discounts
    ]
    v.cite(r.effective_date_citation, "effective_date")
    v.cite(r.end_date_citation, "end_date")

    c = r.confidence
    conf = {
        "customer_and_dates": c.customer_and_dates
        if not v.flagged(("effective_date", "end_date"))
        else min(c.customer_and_dates, 0.5),
        "prices": c.prices if not v.flagged("prices") else min(c.prices, 0.5),
        "escalation": c.escalation if not v.flagged("escalation") else min(c.escalation, 0.5),
        "amendments": c.amendments if not v.flagged("amendments") else min(c.amendments, 0.5),
        "discounts": c.discounts if not v.flagged("discounts") else min(c.discounts, 0.5),
    }
    terms = ContractTerms(
        contract_id=contract_id,
        customer_name=r.customer_name.strip(),
        currency=r.currency or "USD",
        effective_date=_date(r.effective_date),
        end_date=_date(r.end_date),
        prices=prices,
        escalation=esc,
        amendments=amendments,
        approved_discounts=discounts,
        field_confidence=conf,
        source="llm",
        prompt_version=PROMPT_VERSION,
    )
    return terms, v.issues
