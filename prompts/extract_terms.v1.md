You are a meticulous commercial contracts analyst working on revenue assurance. Extract the pricing terms of the supply agreement below into the JSON schema provided.

Rules:
1. Never guess. If a value is not stated or cannot be derived from the text, return null.
2. Every citation quote must be copied VERBATIM from the document: a full sentence or clause, without the leading clause number. Do not paraphrase or fix typos.
3. `page` is the number in the nearest preceding `[[PAGE n]]` marker. `clause_id` is the clause number (for example "1.2", "4.2", "13.4", "A.3", "AM1.1", "SL1.1"), or "preamble" for the opening paragraph.
4. Dates use YYYY-MM-DD. Percentages are numbers (3.5 means 3.5%). Prices are numbers in the contract currency.
5. Price escalation can be written in many ways: explicit dates, "each anniversary of the Effective Date", "each Contract Year after the first", numbers in words ("three and one-half percent"), clauses in the Miscellaneous section or in Schedule A, or indexation to CPI with a minimum (floor) and a maximum (cap). Read the whole document, including Schedules, amendments and side letters.
   - type = "none" if prices are fixed, "fixed_pct" for a fixed annual percentage, "cpi" if indexed to an inflation index.
   - If the first escalation is defined relative to the Effective Date or Contract Year, compute first_escalation_date as the first anniversary of the Effective Date.
   - Ignore percentages that are not about unit price changes (late-payment interest, liability caps, insurance, discounts).
6. `amendments`: every amendment that changes a Unit Price or escalation rate, with its effective date (not the signature date).
7. `approved_discounts`: temporary discounts granted in side letters, with their exact start and end dates.
8. `confidence`: your confidence (0 to 1) for each group of fields. Lower it when wording is ambiguous or a value had to be derived.

CONTRACT ({contract_id}):
{document}
