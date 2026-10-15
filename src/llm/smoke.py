"""Day 1 smoke test: one schema-constrained Gemini call.

python -m src.llm.smoke                # extract terms from a sample clause
python -m src.llm.smoke --list-models  # show models available to your key
"""

from __future__ import annotations

import sys
from decimal import Decimal

from pydantic import BaseModel

from src.llm.client import GeminiClient, get_client

SAMPLE = (
    "7.2 Price Adjustment. Commencing on the first anniversary of the Effective Date "
    "(1 March 2025) and on each anniversary thereafter, the Unit Prices set out in "
    "Schedule A shall increase by three and one-half percent (3.5%)."
)


class SmokeEscalation(BaseModel):
    rate_pct: float
    first_escalation_date: str
    clause_id: str
    quote: str


def main() -> int:
    llm = get_client(cache_mode="off")
    if "--list-models" in sys.argv and isinstance(llm, GeminiClient):
        for name in llm.list_models():
            print(name)
        return 0
    prompt = (
        "Extract the price escalation from this contract clause. Dates as YYYY-MM-DD. "
        "quote must be copied verbatim from the clause.\n\n" + SAMPLE
    )
    data = llm.generate_json(prompt, schema=SmokeEscalation, prompt_version="smoke.v1")
    parsed = SmokeEscalation.model_validate(data)
    print(f"Model: {llm.model}")
    print(parsed.model_dump_json(indent=2))
    ok = (
        Decimal(str(parsed.rate_pct)) == Decimal("3.5")
        and parsed.first_escalation_date == "2025-03-01"
        and parsed.quote.strip().rstrip(".") in SAMPLE
    )
    print("SMOKE TEST PASSED" if ok else "SMOKE TEST: response received but values differ - review")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
