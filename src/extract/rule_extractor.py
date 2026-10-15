"""Regex baseline extractor - what a conventional rules approach achieves.

It handles the standard phrasing ("increase by 3% on 1 March 2025") but has no way to
resolve relative dates ("first anniversary of the Effective Date"), numbers in words,
or unusual verbs. It is kept as the honest comparison for the AI-vs-rules demo view.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from src.extract.document_loader import ClauseChunk, Page, load_document, segment_clauses
from src.schema import Amendment, ApprovedDiscount, Citation, ContractTerms, Escalation, SkuPrice

DATE = r"(\d{1,2} [A-Z][a-z]+ \d{4}|[A-Z][a-z]+ \d{1,2}, \d{4})"
PCT = r"(\d+(?:\.\d+)?)\s?%"


def parse_date(s: str) -> date | None:
    for fmt in ("%d %B %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    return None


def _cite(ch: ClauseChunk) -> Citation:
    return Citation(clause_id=ch.clause_id, page=ch.page, quote=ch.text)


SIMPLE_ESCALATION = re.compile(
    r"non-?compounding|not compound|simple (?:annual )?(?:increase|escalation|interest)|"
    r"of the (?:original|base|initial) (?:Unit )?Price",
    re.I,
)


def _compounding(text: str) -> bool:
    """False only when the clause says the increase is simple; otherwise the D-004 default."""
    return not SIMPLE_ESCALATION.search(text)


def _confidence(esc: Escalation) -> dict[str, float]:
    """Regex cannot judge its own accuracy, but it knows when it failed to resolve a term."""
    unresolved = esc.type != "none" and (
        esc.first_escalation_date is None or (esc.type == "fixed_pct" and esc.rate_pct is None)
    )
    return {"all": 1.0, "escalation": 0.3 if unresolved else 1.0}


def extract(
    path: Path, contract_id: str | None = None, pages: list[Page] | None = None
) -> ContractTerms:
    pages = pages or load_document(path)
    text = re.sub(r"\s+", " ", " ".join(p.text for p in pages))
    clauses = segment_clauses(pages)
    contract_id = contract_id or Path(path).stem

    m = re.search(r'and (.+?) \("Customer"\)', text)
    customer = m.group(1).strip() if m else "UNKNOWN"
    m = re.search(r'"Effective Date" means ' + DATE, text)
    eff = parse_date(m.group(1)) if m else None
    m = re.search(r"continues until " + DATE, text)
    end = parse_date(m.group(1)) if m else None

    prices = []
    for ch in clauses:
        pm = re.match(r"([A-Z]{3}-\d{4}) - (.+?): USD ([\d,]+\.\d{2}) per unit", ch.text)
        if pm:
            prices.append(
                SkuPrice(
                    sku=pm.group(1),
                    description=pm.group(2),
                    unit_price=Decimal(pm.group(3).replace(",", "")),
                    citation=_cite(ch),
                )
            )

    esc = Escalation(type="none")
    for ch in clauses:
        low = ch.text.lower()
        if ch.clause_id.startswith(("AM", "SL")):
            continue
        if "cpi" in low or "consumer price index" in low:
            lo = re.search(r"(?:less than|minimum increase of)[^%]*?" + PCT, ch.text)
            hi = re.search(r"(?:greater than|maximum increase of)[^%]*?" + PCT, ch.text)
            dm = re.search(r"(?:Commencing|on) " + DATE, ch.text)
            esc = Escalation(
                type="cpi",
                floor_pct=Decimal(lo.group(1)) if lo else None,
                cap_pct=Decimal(hi.group(1)) if hi else None,
                first_escalation_date=parse_date(dm.group(1)) if dm else None,
                citation=_cite(ch),
            )
            break
        rm = re.search(r"(?:increase|uplift|escalat\w*|adjust\w*)\D{0,40}?" + PCT, ch.text, re.I)
        if rm:
            dm = re.search(r"(?:on|commencing|from|effective) " + DATE, ch.text, re.I)
            esc = Escalation(
                type="fixed_pct",
                rate_pct=Decimal(rm.group(1)),
                first_escalation_date=parse_date(dm.group(1)) if dm else None,
                compounding=_compounding(ch.text),
                citation=_cite(ch),
            )
            break

    amendments, discounts = [], []
    for ch in clauses:
        am = re.search(
            r"With effect from "
            + DATE
            + r", the Unit Price for ([A-Z]{3}-\d{4}).*?USD ([\d,]+\.\d{2})",
            ch.text,
        )
        if am and ch.clause_id.startswith("AM"):
            amendments.append(
                Amendment(
                    amendment_id=ch.clause_id.split(".")[0],
                    effective_date=parse_date(am.group(1)),
                    sku=am.group(2),
                    new_unit_price=Decimal(am.group(3).replace(",", "")),
                    citation=_cite(ch),
                )
            )
        dm = re.search(
            r"from "
            + DATE
            + r" to "
            + DATE
            + r".*?\("
            + PCT
            + r"\) on the Unit Price of ([A-Z]{3}-\d{4})",
            ch.text,
        )
        if dm and ch.clause_id.startswith("SL"):
            discounts.append(
                ApprovedDiscount(
                    sku=dm.group(4),
                    discount_pct=Decimal(dm.group(3)),
                    start_date=parse_date(dm.group(1)),
                    end_date=parse_date(dm.group(2)),
                    citation=_cite(ch),
                )
            )

    return ContractTerms(
        contract_id=contract_id,
        customer_name=customer,
        effective_date=eff or date(1900, 1, 1),
        end_date=end or date(1900, 1, 1),
        prices=prices,
        escalation=esc,
        amendments=amendments,
        approved_discounts=discounts,
        field_confidence=_confidence(esc),
        source="rule",
    )
