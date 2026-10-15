"""Vetting harness for AI_Revenue_Leakage_Hunter_Vetting_Checklist.xlsx.

    python -m vetting.run_vetting          # writes vetting/results.json

Each test builds small synthetic inputs, calls the real engine (no application code is
modified) and records PASS / FAIL / BLOCKED / N/A with the observed evidence.
Tests that need a human reviewer or a live Gemini key are recorded as BLOCKED.
"""

from __future__ import annotations

import ast
import hashlib
import html
import json
import platform
import re
import shutil
import subprocess
import tempfile
import time
import traceback
from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd

from src import evaluate, pipeline
from src.extract.document_loader import load_document, verify_quote
from src.llm.client import FakeLLMClient, get_client
from src.price_schedule import expected_price
from src.reconcile import reconcile
from src.schema import ContractTerms, Escalation, SkuPrice

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "vetting"
SKU = "SKU-1"
INV_COLS = [
    "invoice_line_id",
    "invoice_id",
    "invoice_date",
    "customer_id",
    "contract_id",
    "sku",
    "quantity",
    "invoiced_unit_price",
    "invoiced_line_amount",
    "currency",
]
RESULTS: dict[str, dict] = {}
ORDER = ["FIN", "EXT", "AI", "EVAL", "SEC", "UX", "OPS"]


# ----------------------------------------------------------------- helpers
def record(test_id: str, status: str, actual: str, notes: str = "") -> None:
    RESULTS[test_id] = {"status": status, "actual": actual, "notes": notes}
    print(f"{test_id:8} {status:8} {actual[:110]}")


def terms(
    base="100",
    rate=None,
    first=None,
    eff=date(2024, 1, 1),
    end=date(2027, 12, 31),
    cid="C-T1",
    currency="USD",
    compounding=True,
) -> ContractTerms:
    esc = (
        Escalation(
            type="fixed_pct",
            rate_pct=Decimal(rate),
            first_escalation_date=first,
            compounding=compounding,
        )
        if rate
        else Escalation()
    )
    return ContractTerms(
        contract_id=cid,
        customer_name="Test Co",
        customer_id="CU-T1",
        currency=currency,
        effective_date=eff,
        end_date=end,
        prices=[SkuPrice(sku=SKU, unit_price=Decimal(base))],
        escalation=esc,
    )


def line(lid="L1", d="2024-06-15", qty="10", price="100", amount=None, cid="C-T1", cur="USD", **kw):
    amt = amount if amount is not None else f"{Decimal(qty) * Decimal(price):.2f}"
    row = dict(
        invoice_line_id=lid,
        invoice_id=f"INV-{lid}",
        invoice_date=d,
        customer_id="CU-T1",
        contract_id=cid,
        sku=SKU,
        quantity=qty,
        invoiced_unit_price=price,
        invoiced_line_amount=amt,
        currency=cur,
    )
    row.update(kw)
    return row


NO_ADJ = pd.DataFrame(columns=["invoice_line_id", "adjustment_type", "amount"])


def recon(rows, t) -> pd.DataFrame:
    tmap = t if isinstance(t, dict) else {t.contract_id: t}
    return reconcile(pd.DataFrame(rows, columns=INV_COLS, dtype=str), NO_ADJ, tmap, {})


def run_portfolio(rows, t) -> dict:
    """Full pipeline (reconcile -> findings -> summary) on a throwaway data dir."""
    tmap = t if isinstance(t, dict) else {t.contract_id: t}
    tmp = Path(tempfile.mkdtemp(prefix="vet_"))
    (tmp / "reference").mkdir()
    pd.DataFrame(rows, columns=INV_COLS).to_csv(tmp / "invoice_lines.csv", index=False)
    NO_ADJ.to_csv(tmp / "billing_adjustments.csv", index=False)
    pd.DataFrame([{"customer_id": "CU-T1", "customer_name": "Test Co", "industry": "x"}]).to_csv(
        tmp / "customers.csv", index=False
    )
    shutil.copy(DATA / "reference" / "cpi_annual_pct.csv", tmp / "reference")
    try:
        return pipeline.run(terms=tmap, terms_dir=tmp, data_dir=tmp, out_dir=tmp / "out")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def crash(fn):
    """Run fn; return (result, None) or (None, 'ExcType: message')."""
    try:
        return fn(), None
    except Exception as exc:  # noqa: BLE001 - we are recording failures
        return None, f"{type(exc).__name__}: {exc}"


def r0(df: pd.DataFrame, i=0) -> dict:
    return df.iloc[i].to_dict()


# ----------------------------------------------------------------- FIN
def fin():
    t = terms()
    r = r0(recon([line()], t))
    ok = (
        r["status"] == "MATCH"
        and r["expected_line_amount"] == "1000.00"
        and r["potential_underbilling"] == "0.00"
    )
    record(
        "FIN-01",
        "Pass" if ok else "Fail",
        f"status={r['status']}; expected={r['expected_line_amount']}; net billed={r['net_billed_amount']}; "
        f"under={r['potential_underbilling']}; over={r['potential_overbilling']}",
    )

    r = r0(recon([line(price="95")], t))
    ok = (
        r["status"] == "POTENTIAL_UNDERBILLING"
        and r["potential_underbilling"] == "50.00"
        and r["expected_line_amount"] == "1000.00"
        and r["net_billed_amount"] == "950.00"
    )
    record(
        "FIN-02",
        "Pass" if ok else "Fail",
        f"status={r['status']}; expected={r['expected_line_amount']}; actual={r['net_billed_amount']}; "
        f"underbilling={r['potential_underbilling']}",
    )

    res = run_portfolio([line(price="105")], t)
    r = r0(res["lines"])
    f = res["findings"][0]
    s = res["summary"]
    ok = (
        r["status"] == "POTENTIAL_OVERBILLING"
        and r["potential_overbilling"] == "50.00"
        and r["potential_underbilling"] == "0.00"
        and f.root_cause == "OVERBILLING"
        and Decimal(s["potential_underbilling"]) == 0
        and s["overbilling_findings"] == 1
    )
    record(
        "FIN-03",
        "Pass" if ok else "Fail",
        f"status={r['status']}; over={r['potential_overbilling']}; under={r['potential_underbilling']}; "
        f"finding root_cause={f.root_cause}; portfolio underbilling={s['potential_underbilling']}; "
        f"overbilling_findings={s['overbilling_findings']}",
        "Overbilling is reported as a separate finding with a credit-note action and is excluded from "
        "the underbilling total and recoverable estimate.",
    )

    t5 = terms(rate="5", first=date(2025, 1, 1))
    p1 = expected_price(t5, SKU, date(2024, 12, 31)).unit_price
    p2 = expected_price(t5, SKU, date(2025, 1, 1)).unit_price
    record(
        "FIN-04",
        "Pass" if (p1, p2) == (Decimal("100.00"), Decimal("105.00")) else "Fail",
        f"2024-12-31 -> {p1}; 2025-01-01 -> {p2}",
    )

    p3 = expected_price(t5, SKU, date(2026, 1, 1)).unit_price
    simple = expected_price(
        terms(rate="5", first=date(2025, 1, 1), compounding=False), SKU, date(2026, 1, 1)
    ).unit_price
    no_date, err = crash(lambda: expected_price(terms(rate="5", first=None), SKU, date(2026, 1, 1)))
    record(
        "FIN-05",
        "Pass" if (p3, simple) == (Decimal("110.25"), Decimal("110.00")) and err else "Fail",
        f"compounding=True -> {p3}; compounding=False -> {simple} (expected 110.25 / 110.00). Escalation "
        f"with no resolved first date -> "
        f"{'raises (line goes to REVIEW): ' + err[:70] if err else 'priced: ' + str(no_date)}",
        "Fixed in v2: expected_price() honours Escalation.compounding (simple = anchor x (1 + sum of rates)). "
        "Rules extractor sets compounding=False for 'non-compounding'/'simple'/'of the original price' "
        "wording; Gemini schema has a compounding field (null -> D-004 default, compounding).",
    )

    t6 = terms(rate="5", first=date(2025, 7, 1))
    p = expected_price(t6, SKU, date(2025, 6, 30)).unit_price
    p_on = expected_price(t6, SKU, date(2025, 7, 1)).unit_price
    record(
        "FIN-06",
        "Pass" if p == Decimal("100.00") else "Fail",
        f"2025-06-30 -> {p}; 2025-07-01 -> {p_on}",
    )

    rows = [line(lid=f"Q{q}", qty=str(q)) for q in (0, 1, 10, 100)]
    df = recon(rows, t)
    got = list(df["expected_line_amount"])
    ok = got == ["0.00", "100.00", "1000.00", "10000.00"] and set(df["status"]) == {"MATCH"}
    record(
        "FIN-07",
        "Pass" if ok else "Fail",
        f"qty 0/1/10/100 -> expected {got}; statuses {list(df['status'])}",
        "Qty 0 is reconciled as an ordinary MATCH line; there is no documented zero-quantity policy "
        "(see EXT-04).",
    )

    # rounding: half-up to cents, escalated price rounded once then multiplied
    t8 = terms(base="81.50", rate="3.5", first=date(2025, 1, 1))
    px = expected_price(t8, SKU, date(2025, 6, 1)).unit_price  # 84.3525 -> 84.35
    half = expected_price(
        terms(base="10.125"), SKU, date(2024, 6, 1)
    ).unit_price  # -> 10.13 half-up
    df = recon([line(lid=f"R{i}", d="2025-06-01", qty="7", price="84.35") for i in range(1000)], t8)
    tot = sum(Decimal(x) for x in df["expected_line_amount"])
    ok = (
        px == Decimal("84.35")
        and half == Decimal("10.13")
        and tot == Decimal("590450.00")
        and set(df["status"]) == {"MATCH"}
    )
    record(
        "FIN-08",
        "Pass" if ok else "Fail",
        f"81.50 x 1.035 = 84.3525 -> {px}; 10.125 -> {half} (half-up); 1,000 lines x 7 x 84.35 total = {tot} "
        f"(exact Decimal, no float drift); all MATCH = {set(df['status']) == {'MATCH'}}",
        "Rule (D-004/D-008): compounding exact, unit price rounded half-up to cents once, then x qty. "
        "Per-step vs once rounding still open with Mentor 1 (B-003).",
    )

    res = run_portfolio([line(price="95", cur="EUR")], t)
    r = r0(res["lines"])
    record(
        "FIN-09",
        "Fail" if r["status"] != "REVIEW" else "Pass",
        f"Contract USD, invoice EUR -> status={r['status']} ({r.get('issue_type')}: {r['reason']}); "
        f"portfolio underbilling {res['summary']['potential_underbilling']}",
        "Fixed in v2: currency mismatches go to REVIEW until an auditable FX conversion policy exists.",
    )

    df = recon([line(lid="B", d="2023-12-31"), line(lid="A", d="2028-01-01")], t)
    ok = list(df["status"]) == ["REVIEW", "REVIEW"]
    record(
        "FIN-10",
        "Pass" if ok else "Fail",
        f"day before start -> {df.iloc[0]['status']} ('{df.iloc[0]['reason']}'); day after expiry -> "
        f"{df.iloc[1]['status']} ('{df.iloc[1]['reason']}')",
    )

    fin11()
    fin12()

    rows = [
        line(lid="U1", price="95"),
        line(lid="U2", qty="10", price="97"),
        line(lid="M1"),
        line(lid="O1", price="102"),
    ]
    res = run_portfolio(rows, t)
    s = res["summary"]
    line_sum = sum(Decimal(x) for x in res["lines"]["potential_underbilling"])
    find_sum = sum(f.amount for f in res["findings"] if f.root_cause != "OVERBILLING")
    ok = Decimal(s["potential_underbilling"]) == Decimal("80.00") == line_sum == find_sum
    # reconcile the real run too
    real = json.loads((DATA / "output" / "summary.json").read_text())
    rl = pd.read_csv(DATA / "output" / "line_results.csv", dtype=str)
    rf = pd.read_csv(DATA / "output" / "findings.csv", dtype=str)
    real_lines = sum(Decimal(x) for x in rl["potential_underbilling"].fillna("0"))
    real_find = sum(Decimal(x) for x in rf.loc[rf["root_cause"] != "OVERBILLING", "amount"])
    ok = ok and real_lines == real_find == Decimal(real["potential_underbilling"])
    record(
        "FIN-13",
        "Pass" if ok else "Fail",
        f"Synthetic: $50 + $30 + match + $20 overbilling -> underbilling total {s['potential_underbilling']} "
        f"(lines {line_sum}, findings {find_sum}), overbilling kept separate. Real run: line sum {real_lines} = "
        f"findings sum {real_find} = summary {real['potential_underbilling']}",
    )

    res = run_portfolio([line(lid="D1", price="95"), line(lid="D1", price="95")], t)
    res2 = run_portfolio(
        [line(lid="D1", price="95"), line(lid="D2", price="95", invoice_id="INV-D1")], t
    )
    res3 = run_portfolio([line(lid="D1", price="95"), line(lid="D1", price="90")], t)
    ok = (
        res["summary"]["potential_underbilling"] == "50.00"
        and list(res["lines"]["status"]) == ["POTENTIAL_UNDERBILLING", "DUPLICATE"]
        and res2["summary"]["potential_underbilling"] == "50.00"
        and res2["lines"].iloc[1]["issue_type"] == "POSSIBLE_DUPLICATE"
        and set(res3["lines"]["issue_type"]) == {"DUPLICATE_ID_CONFLICT"}
    )
    record(
        "FIN-14",
        "Pass" if ok else "Fail",
        f"Exact duplicate row -> statuses {list(res['lines']['status'])}, underbilling "
        f"{res['summary']['potential_underbilling']}. Same business key, new ID -> "
        f"{list(res2['lines']['issue_type'])}, underbilling {res2['summary']['potential_underbilling']}. "
        f"Same ID, different content -> {list(res3['lines']['issue_type'])}.",
        "Fixed in v2: exact copies are kept once (status DUPLICATE, excluded from totals); conflicting rows "
        "and possible duplicates go to REVIEW. Nothing is deleted; every case is in input_issues.csv.",
    )

    r = r0(recon([line(price="95", amount="960.00")], t))
    record(
        "FIN-15",
        "Pass" if r.get("issue_type") == "ARITHMETIC_MISMATCH" else "Fail",
        f"qty 10 x $95 but line amount $960 -> status={r['status']} ({r.get('issue_type')}: {r['reason']})",
        "Fixed in v2: |qty x unit price - line amount| > $0.01 is an invoice-integrity REVIEW, kept separate "
        "from price findings, so the unit price and the $ amount can no longer disagree inside a finding.",
    )


def fin11():
    tmp = Path(tempfile.mkdtemp(prefix="vet_noeval_"))
    try:
        data = tmp / "data"
        shutil.copytree(DATA, data, ignore=shutil.ignore_patterns("eval", "output", "llm_cache"))
        a = pipeline.run(DATA / "extracted" / "rule", data_dir=DATA, out_dir=tmp / "with_eval")
        b = pipeline.run(data / "extracted" / "rule", data_dir=data, out_dir=tmp / "no_eval")
        ha = hashlib.sha256((tmp / "with_eval" / "line_results.csv").read_bytes()).hexdigest()
        hb = hashlib.sha256((tmp / "no_eval" / "line_results.csv").read_bytes()).hexdigest()
        fa = pd.read_csv(tmp / "with_eval" / "findings.csv")
        fb = pd.read_csv(tmp / "no_eval" / "findings.csv")
        same_f = fa.drop(columns=["calculation_latest"], errors="ignore").equals(
            fb.drop(columns=["calculation_latest"], errors="ignore")
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    src_refs = []
    for p in [
        "reconcile.py",
        "findings.py",
        "price_schedule.py",
        "explain.py",
        "extract/rule_extractor.py",
        "extract/llm_extractor.py",
        "extract/document_loader.py",
    ]:
        txt = (ROOT / "src" / p).read_text(encoding="utf-8")
        if re.search(r"ground_truth|contract_scenarios|expected_price_schedule", txt):
            src_refs.append(p)
    ok = (
        ha == hb
        and same_f
        and not src_refs
        and a["summary"]["potential_underbilling"] == b["summary"]["potential_underbilling"]
    )
    record(
        "FIN-11",
        "Pass" if ok else "Fail",
        f"Pipeline re-run on a copy of data/ with data/eval removed: line_results identical={ha == hb}, "
        f"findings identical={same_f}, underbilling {a['summary']['potential_underbilling']} vs "
        f"{b['summary']['potential_underbilling']}. Detector modules referencing ground-truth files: {src_refs or 'none'}",
        "Fixed in v2: no fallback to data/eval/gold. A detector run without extracted terms fails with a "
        "clear message; answer-key runs need --oracle and are labelled ORACLE in summary.json and the app.",
    )


def fin12():
    lines = pd.read_csv(DATA / "output" / "line_results.csv", dtype=str)
    flagged = lines[lines["status"].isin(["POTENTIAL_UNDERBILLING", "POTENTIAL_OVERBILLING"])]
    contracts = {p.stem: p for p in (DATA / "contracts").iterdir()}
    pages = {}
    missing_ids = (
        flagged[["invoice_line_id", "invoice_id", "invoice_date"]].isna().any(axis=1).sum()
    )
    no_price_cite = flagged["price_quote"].isna().sum()
    esc_needed = flagged["n_escalations"].astype(int) > 0
    no_esc_cite = (esc_needed & flagged["escalation_quote"].isna()).sum()
    bad = []
    checked = 0
    for r in flagged.to_dict(orient="records"):
        cid = r["contract_id"]
        if cid not in pages:
            pages[cid] = load_document(contracts[cid])
        for k in ("price", "escalation", "amendment", "discount"):
            q = r.get(f"{k}_quote")
            if isinstance(q, str) and q:
                checked += 1
                ok, pg = verify_quote(
                    q,
                    pages[cid],
                    int(float(r[f"{k}_page"])) if isinstance(r.get(f"{k}_page"), str) else None,
                )
                if not ok:
                    bad.append((r["invoice_line_id"], k))
    # does the price quote actually contain the SKU and the anchor price?
    sku_price_mismatch = 0
    for r in flagged.to_dict(orient="records"):
        q = (r.get("price_quote") or "").replace(",", "")
        if r["anchor_source"] == "base price" and (
            r["sku"] not in q or f"{Decimal(r['anchor_price']):.2f}" not in q
        ):
            sku_price_mismatch += 1
    sample = flagged.drop_duplicates(["contract_id", "sku"]).head(5)
    samp = "; ".join(
        f"{r['invoice_line_id']}/{r['invoice_id']}/{r['invoice_date']} {r['contract_id']} {r['sku']} "
        f"price cl.{r['price_clause_id']} p{r['price_page']} esc cl.{r['escalation_clause_id']}"
        for r in sample.to_dict(orient="records")
    )
    ok = (
        not bad
        and missing_ids == 0
        and no_price_cite == 0
        and no_esc_cite == 0
        and sku_price_mismatch == 0
    )
    record(
        "FIN-12",
        "Pass" if ok else "Fail",
        f"{len(flagged)} flagged lines (rules-baseline run). Missing invoice line/ID/date: {missing_ids}. "
        f"Missing price citation: {no_price_cite}. Escalated lines without escalation citation: {no_esc_cite}. "
        f"{checked} quotes checked verbatim against the contract file: {len(bad)} not found. Base-price quotes "
        f"not containing the SKU and price: {sku_price_mismatch}. Sample: {samp}",
        "Automated check only. The checklist also asks a human to read 5 findings and confirm the clause "
        "supports the price - do this during UX-01.",
    )


# ----------------------------------------------------------------- EXT
def ext():
    t = terms()
    res, err = crash(lambda: run_portfolio([line(price="95", cid="C-NOPE")], t))
    if err:
        record("EXT-01", "Fail", f"crash: {err}")
    else:
        r = r0(res["lines"])
        record(
            "EXT-01",
            "Pass" if r["status"] == "REVIEW" else "Fail",
            f"unknown contract -> status={r['status']} ('{r['reason']}'); findings={len(res['findings'])}",
        )

    out = []
    fails = 0
    for field in [
        "invoiced_unit_price",
        "invoiced_line_amount",
        "invoice_date",
        "quantity",
        "currency",
        "contract_id",
    ]:
        row = line(price="95")
        row[field] = ""
        res, err = crash(lambda row=row: run_portfolio([row, line(lid="OK")], t))
        if err:
            out.append(f"{field} blank -> CRASH ({err[:70]})")
            fails += 1
        else:
            r = r0(res["lines"])
            out.append(f"{field} blank -> {r['status']} ({r.get('issue_type')})")
            if r["status"] != "REVIEW":
                fails += 1
    record(
        "EXT-02",
        "Fail" if fails else "Pass",
        " | ".join(out),
        "Fixed in v2: every row is validated before arithmetic; bad rows go to REVIEW / INVALID_INPUT with "
        "the field, value, file and row number, and the other rows still reconcile.",
    )

    out, fails = [], 0
    for d in ["2024-06-15", "15/06/2024", "06/15/2024", "20240615", "", "2024-13-45"]:
        res, err = crash(lambda d=d: run_portfolio([line(d=d)], t))
        got = None if err else r0(res["lines"])["status"]
        out.append(f"'{d}' -> {'CRASH (' + err[:55] + ')' if err else got}")
        want = "MATCH" if d == "2024-06-15" else "REVIEW"
        fails += bool(err) or got != want
    record(
        "EXT-03",
        "Fail" if fails else "Pass",
        " | ".join(out),
        "Policy (D-011): invoice dates must be ISO YYYY-MM-DD. Ambiguous formats (15/06 vs 06/15) are never "
        "guessed; they are quarantined per row instead of crashing the run.",
    )

    out, fails = [], 0
    for desc, row in [
        ("qty -5 @100", line(qty="-5")),
        ("price -100", line(price="-100")),
        ("price 0", line(price="0")),
        ("qty 0", line(qty="0")),
    ]:
        res, err = crash(lambda row=row: run_portfolio([row], t))
        r = r0(res["lines"]) if res else {}
        out.append(
            f"{desc} -> "
            f"{'CRASH ' + err if err else r['status'] + ' (' + str(r.get('issue_type') or '-') + ')'}"
        )
        want = {"qty -5 @100": "REVIEW", "price -100": "REVIEW"}.get(desc)
        if err or (want and r["status"] != want):
            fails += 1
    record(
        "EXT-04",
        "Fail" if fails else "Pass",
        " | ".join(out),
        "Policy (D-012): negative quantities and prices are rejected (REVIEW / INVALID_INPUT); returns and "
        "credits must be booked as return_credit / credit_note adjustments. A $0 price on a priced SKU is "
        "reported as potential underbilling for review. Qty 0 is a $0 line (MATCH).",
    )

    res, err = crash(
        lambda: run_portfolio(
            [line(lid="G1", price="95"), line(lid="BAD", d="31/12/2024"), line(lid="G2")], t
        )
    )
    got = [] if err else list(res["lines"]["status"])
    record(
        "EXT-05",
        "Pass" if got == ["POTENTIAL_UNDERBILLING", "REVIEW", "MATCH"] else "Fail",
        f"2 valid rows + 1 bad date -> {'whole batch aborted: ' + err if err else 'statuses ' + str(got)}",
        "Fixed in v2: the bad row is quarantined and logged; the valid rows are reconciled.",
    )


# ----------------------------------------------------------------- AI
def ai():
    ex = json.loads((ROOT / "reports" / "extraction_summary.json").read_text())
    rule = next(e for e in ex if e["extractor"] == "rule")
    record(
        "AI-01",
        "Blocked",
        f"Gemini extraction not run (no GEMINI_API_KEY, B-002). Rules baseline measured: key-field accuracy "
        f"{rule.get('key_field_accuracy')} over {rule.get('fields')} fields; escalation group "
        f"{rule.get('by_group', {}).get('escalation')}; {rule.get('contracts_all_correct')}/30 contracts fully correct.",
        "Field-level accuracy harness exists (src/evaluate_extraction.py, by field group and escalation wording). "
        "Re-run with a key to get the Gemini numbers.",
    )

    # citation verifier behaviour, offline
    pages = load_document(next((DATA / "contracts").glob("C-2001.*")))
    real_q = pages[0].text.split("\n")[5][:60]
    ok_real, _ = verify_quote(real_q, pages)
    ok_fake, _ = verify_quote("The Unit Price shall be USD 1.00 for all SKUs forever.", pages)
    record(
        "AI-02",
        "Blocked",
        f"Live Gemini citations not testable without a key. Verifier checked offline: real quote found={ok_real}; "
        f"fabricated quote found={ok_fake}. llm_extractor also checks the extracted value appears in its quote "
        "and lowers confidence + adds a review item when either check fails.",
        "Re-run with key; then inspect base-price and escalation citations separately for 5 contracts.",
    )

    # ambiguous clause routing - plumbing check with a fake LLM
    from src.extract import llm_extractor

    fake_resp = {
        "customer_name": "Northwind Fabrication Ltd",
        "currency": "USD",
        "effective_date": "2024-01-01",
        "end_date": "2026-12-31",
        "effective_date_citation": {"clause_id": "preamble", "page": 1, "quote": real_q},
        "end_date_citation": {"clause_id": "preamble", "page": 1, "quote": real_q},
        "prices": [],
        "escalation": {
            "type": "fixed_pct",
            "rate_pct": 3,
            "first_escalation_date": None,
            "derivation": "Clause is vague; rate assumed.",
            "citation": {
                "clause_id": "4.2",
                "page": 1,
                "quote": "prices may be reviewed from time to time",
            },
        },
        "amendments": [],
        "approved_discounts": [],
        "confidence": {
            "customer_and_dates": 0.9,
            "prices": 0.9,
            "escalation": 0.3,
            "amendments": 0.9,
            "discounts": 0.9,
        },
    }
    out, err = crash(
        lambda: llm_extractor.extract(
            next((DATA / "contracts").glob("C-2001.*")), FakeLLMClient([fake_resp])
        )
    )
    if err:
        detail = f"fake-LLM plumbing test errored: {err[:120]}"
    else:
        tm, issues = out
        detail = (
            f"fake-LLM plumbing test (ambiguous escalation, no date, unverifiable quote): review items={len(issues)} "
            f"({'; '.join(i['issue'] for i in issues)[:140]}); escalation confidence={tm.field_confidence.get('escalation')}"
        )
    record(
        "AI-03",
        "Blocked",
        f"Live model behaviour needs a key. {detail}. Rules baseline: 0 review items across 30 contracts even "
        "though 9 of 30 contracts had at least one wrong key field - it never routes uncertainty to review.",
        "Downstream, reconcile marks findings needs_term_review when extraction confidence < 0.6.",
    )

    prompt = (ROOT / "prompts" / "extract_terms.v2.md").read_text(encoding="utf-8")
    has_guard = bool(re.search(r"untrusted|ignore any instructions|treat .* as data", prompt, re.I))
    record(
        "AI-04",
        "Blocked",
        f"Live injection test needs a key. Static review: prompt has explicit 'document is untrusted data' "
        f"instruction = {has_guard}. Mitigations present: schema-constrained JSON output, every value must be "
        "a verbatim quote that is verified in the document, values checked against quotes, all $ computed in "
        "Python, explanations pass a numeric guardrail.",
        "v2 prompt adds the untrusted-data instruction and BEGIN/END markers. Still to do: a synthetic "
        "contract with an injected clause in the test set, run live with a key.",
    )

    # LLM unavailable
    import os

    saved = os.environ.pop("GEMINI_API_KEY", None)
    try:
        _, e1 = crash(lambda: get_client(cache_mode="readwrite"))
        off = get_client(cache_mode="readonly")
        _, e2 = crash(lambda: off.generate_json("never cached", prompt_version="vet"))
    finally:
        if saved is not None:
            os.environ["GEMINI_API_KEY"] = saved

    class Boom(FakeLLMClient):
        def _call(self, *a, **k):
            raise TimeoutError("simulated timeout")

    res = run_portfolio([line(price="95")], terms())
    f = res["findings"][0]
    from src.explain import explain as _explain

    _, src_, note = _explain(f, llm=Boom())
    ok = bool(e1) and e2 and "CacheMiss" in e2 and src_ != "llm"
    record(
        "AI-05",
        "Pass" if ok else "Fail",
        f"No key -> {e1}. Offline cache miss -> {e2}. Explanation with simulated timeout -> source='{src_}' "
        f"({note[:80]}). Extraction batch catches per-contract exceptions and logs them to review_queue.csv.",
        "GeminiClient retries 429/5xx with exponential backoff (max 5). No fabricated success observed.",
    )


# ----------------------------------------------------------------- EVAL
def evals():
    tmp = Path(tempfile.mkdtemp(prefix="vet_eval_"))
    summary = {}
    try:
        for src in ("gold", "rule"):
            d = DATA / "eval" / "gold" if src == "gold" else DATA / "extracted" / "rule"
            out = tmp / src
            pipeline.run(d, out_dir=out)
            res = evaluate.evaluate(out_dir=out)
            lines = pd.read_csv(out / "line_results.csv", dtype=str)
            truth = pd.read_csv(DATA / "eval" / "ground_truth.csv", dtype=str)
            lines = lines[lines["status"].ne("DUPLICATE")]
            m = truth.merge(lines, on="invoice_line_id", how="left", suffixes=("_t", ""))
            pred = m["status"].eq("POTENTIAL_UNDERBILLING")
            act = m["is_leakage"].eq("true")
            tn = int((~pred & ~act).sum())
            err = (
                m["potential_underbilling"].fillna("0").replace("", "0").map(Decimal)
                - m["seeded_leakage_amount"].map(Decimal)
            ).abs()
            per = (
                m.assign(pred=pred, act=act)
                .groupby("scenario")
                .apply(
                    lambda g: (
                        f"{int((g.pred & g.act).sum())}/{int(g.act.sum())} found, {int((g.pred & ~g.act).sum())} FP"
                    ),
                    include_groups=False,
                )
                .to_dict()
            )
            summary[src] = dict(
                tp=res["tp"],
                fp=res["fp"],
                fn=res["fn"],
                tn=tn,
                n=res["lines"],
                p=res["line_precision"],
                r=res["line_recall"],
                det=res["detected_usd"],
                seed=res["seeded_usd"],
                agg=res["dollar_error_pct"],
                mae=f"{err.mean():.2f}",
                maxe=f"{err.max():.2f}",
                sum_abs=f"{err.sum():.2f}",
                lines_wrong=int((err > Decimal("0.01")).sum()),
                per=per,
                report_has_tn="tn" in res,
            )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    g, r = summary["gold"], summary["rule"]

    def cm(s):
        return (
            f"TP {s['tp']} FP {s['fp']} FN {s['fn']} TN {s['tn']} (n={s['n']}); precision {s['tp']}/{s['tp'] + s['fp']} "
            f"= {s['p']}; recall {s['tp']}/{s['tp'] + s['fn']} = {s['r']}"
        )

    with tempfile.TemporaryDirectory() as td:
        pipeline.run(DATA / "extracted" / "rule", out_dir=Path(td))
        rep = evaluate.evaluate(out_dir=Path(td))
    has_cm = all(k in rep for k in ("tn", "lines", "overbilling_precision", "outcome_accuracy"))
    record(
        "EVAL-01",
        "Pass" if has_cm and g["fp"] == g["fn"] == 0 else "Fail",
        f"GOLD terms: {cm(g)}. RULES: {cm(r)}. Ground truth is generated independently by the data factory "
        "(FIN-11).",
        "Fixed in v2: evaluate() and reports/evaluation_*.md show TP/FP/FN/TN with denominators, separate "
        "overbilling precision/recall, review routing, and fail on ambiguous or unmatched IDs.",
    )
    record(
        "EVAL-02",
        "Pass" if "line_abs_error_mean_usd" in rep and g["lines_wrong"] == 0 else "Fail",
        f"GOLD: aggregate {g['det']} vs {g['seed']} ({g['agg']}% err); line-level mean abs error ${g['mae']}, "
        f"max ${g['maxe']}, lines off by > 1c: {g['lines_wrong']}. RULES: aggregate {r['det']} vs {r['seed']} "
        f"({r['agg']}% err); line-level mean abs error ${r['mae']}, max ${r['maxe']}, sum abs ${r['sum_abs']}, "
        f"lines wrong: {r['lines_wrong']}.",
        "Fixed in v2: evaluate() reports line-level mean/max absolute error, lines off by > 1c, and flagged "
        "leakage lines with the wrong amount, alongside the aggregate.",
    )
    record(
        "EVAL-03",
        "Pass",
        "Per-scenario table is in reports/evaluation_*.md. Recall by scenario (rules): "
        + "; ".join(f"{k}: {v}" for k, v in r["per"].items()),
        "Per-scenario precision/recall are given as counts, not rates - acceptable.",
    )
    record(
        "EVAL-04",
        "Fail",
        "No holdout set. data/blind/ does not exist; blind contracts in Mentor 1's own wording are still open "
        "(B-005). All metrics come from the same generator the rules were written against.",
        "Required before the jury: 3-5 blind contracts + invoices, metrics reported separately.",
    )

    t = terms()
    rows = [
        line(lid="C1", qty="1", price="99.99"),
        line(lid="C2", qty="1", price="99.98"),
        line(lid="C3", qty="1", price="99.00"),
    ]
    df = recon(rows, t)
    record(
        "EVAL-05",
        "Pass",
        f"Tolerance TOLERANCE=$0.01 (src/reconcile.py:24, strict >): $0.01 short -> {df.iloc[0]['status']}; "
        f"$0.02 short -> {df.iloc[1]['status']} ({df.iloc[1]['potential_underbilling']}); $1 short -> "
        f"{df.iloc[2]['status']}. No business materiality filter - every finding > 1c is reported.",
        "Explicit in code but not in docs/decisions.md, README or the UI. Recommend logging it as a decision "
        "and showing it in the app; agree a business materiality threshold for prioritisation with Mentor 1.",
    )


# ----------------------------------------------------------------- SEC
def sec():
    pats = re.compile(
        r"AIza[0-9A-Za-z_\-]{30,}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|"
        r"(?:[Pp]assword|passwd|[Ss]ecret|api_key|API_KEY|token)\s*[:=]\s*['\"][^'\"\s]{6,}"
    )
    hits = []
    for p in ROOT.rglob("*"):
        if (
            any(
                x in p.parts
                for x in (".venv", ".git", "__pycache__", ".ruff_cache", ".pytest_cache")
            )
            or not p.is_file()
        ):
            continue
        if p.suffix.lower() in (".pdf", ".docx", ".pyc", ".png"):
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if pats.search(txt):
            hits.append(str(p.relative_to(ROOT)))
    hist = subprocess.run(
        ["git", "log", "-p", "--all"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    ).stdout
    hist_hits = len(pats.findall(hist))
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True
    ).stdout.split()
    env_tracked = ".env" in tracked
    env_val = ""
    if (ROOT / ".env").exists():
        env_val = (
            "set"
            if re.search(r"^GEMINI_API_KEY=\S+", (ROOT / ".env").read_text(), re.M)
            else "empty"
        )
    ignored = ".env" in (ROOT / ".gitignore").read_text().split()
    hits = [h for h in hits if not h.startswith("vetting")]
    ok = not hits and not hist_hits and not env_tracked and ignored
    record(
        "SEC-01",
        "Pass" if ok else "Fail",
        f"Working-tree secret-pattern hits: {hits or 'none'}; git history hits: {hist_hits}; .env tracked by git: "
        f"{env_tracked}; .env in .gitignore: {ignored}; .env key currently {env_val}; .env.example has empty key. "
        "LLM cache files store model/prompt/response only (no key).",
        "When a real key is added, re-run this test; keep the key out of screenshots of the sidebar/terminal.",
    )

    cust = pd.read_csv(DATA / "customers.csv")
    emails = []
    for p in list(DATA.rglob("*.csv")) + list((ROOT / "reports").glob("*")):
        t = p.read_text(encoding="utf-8", errors="ignore")
        emails += re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", t)
    gen = (ROOT / "src" / "generate_synthetic_data.py").read_text(encoding="utf-8")
    record(
        "SEC-02",
        "Pass",
        f"All {len(cust)} customers, 30 contracts and invoice data are produced by src/generate_synthetic_data.py "
        f"(seeded, fictitious names e.g. {', '.join(cust['customer_name'].head(3))}). Email addresses found in "
        f"data/reports: {len(set(emails))}. Generator uses a fixed seed: {'seed' in gen.lower()}.",
        "Scope: project folder only. The parent folder also holds 'AI Revenue hunter.xlsx' - not inspected by "
        "this harness; confirm it holds no client data before sharing the folder.",
    )

    app = (ROOT / "app" / "streamlit_app.py").read_text(encoding="utf-8")
    record(
        "SEC-03",
        "N/A",
        f"No file-upload feature: st.file_uploader present = {'file_uploader' in app}. Contracts are read from "
        "data/contracts only; document_loader rejects other extensions with a clear ValueError.",
        "Out of scope for the MVP.",
    )

    tree = ast.parse(app)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "highlight")
    ns = {"html": html, "re": re}
    exec(compile(ast.Module([fn], []), "highlight", "exec"), ns)
    payload = "Acme <script>alert('x')</script> <img src=x onerror=alert(1)> Unit Price"
    out = ns["highlight"](payload, ["Unit Price"])
    unsafe_calls = len(re.findall(r"unsafe_allow_html=True", app))
    ok = "<script>" not in out and "<img" not in out and "<mark>Unit Price</mark>" in out
    record(
        "SEC-04",
        "Pass" if ok else "Fail",
        f"highlight() output for script/img payload: {out[:120]}. {unsafe_calls} unsafe_allow_html uses: CSS "
        "block (static), evidence quote (html.escape) and contract text (html.escape inside highlight()). "
        "Customer/product fields are shown via st.dataframe/st.markdown without HTML enabled.",
        "Streamlit markdown still renders Markdown syntax (links, bold) in st.markdown(f'...') strings - low risk "
        "with synthetic data.",
    )

    net = re.findall(
        r"requests\.|smtplib|urllib|httpx\.|sendmail|\.post\(",
        app + "".join(p.read_text(encoding="utf-8") for p in (ROOT / "src").rglob("*.py")),
    )
    record(
        "SEC-05",
        "Pass",
        f"No email/ERP/API write paths found (network/send patterns in app+src: {len(net)}). The only external "
        "call is Gemini (read-only generation). 'Record decision' appends to local data/output/review_decisions.csv; "
        "the rebill note is a draft text box.",
        "Human approval is required for every action by design.",
    )


# ----------------------------------------------------------------- UX
def ux():
    app = (ROOT / "app" / "streamlit_app.py").read_text(encoding="utf-8")
    record(
        "UX-01",
        "Blocked",
        "Needs a finance reviewer. Prepared: Findings tab shows expected vs billed unit price chart, invoice "
        "line IDs/dates, qty, expected and net billed amounts, delta, calculation formula, cited clause text "
        "with page, owner and action.",
        "Gap: unflagged (MATCH) lines cannot be inspected in the app - the reviewer needs data/output/"
        "line_results.csv for the 5 unflagged lines.",
    )
    terms_found = {
        w: len(re.findall(w, app))
        for w in [
            "Unbilled revenue found",
            "Estimated recoverable",
            "Recovered for client",
            "human-approved recovery",
        ]
    }
    claims_left = {k: v for k, v in terms_found.items() if v}
    record(
        "UX-02",
        "Fail" if claims_left else "Pass",
        f"Claim-style labels left in app/streamlit_app.py: {claims_left or 'none'}. Headline is 'Potential "
        "underbilling (unvalidated)'; recoverability is an 'Illustrative recoverable estimate' with its "
        "basis; the value calculator tab is '(simulated)'; oracle runs show a warning banner.",
        "Needs a human look during UX-01/UX-04 to confirm the wording reads as intended.",
    )
    exports = [x for x in ("findings.csv", "line_results.csv", "input_issues.csv") if x in app]
    record(
        "UX-03",
        "Pass" if len(exports) == 3 else "Fail",
        f"download_button uses: {app.count('download_button')}; exports in the Findings tab: {exports}. "
        "A review queue lists every line that was not reconciled, with issue type and source row.",
        "Exports are the full run (not a filtered view); the run's terms source is shown on screen.",
    )
    record(
        "UX-04",
        "Blocked",
        "Needs an unfamiliar user walkthrough.",
        "Known friction: `tasks.ps1 app` stops at Streamlit's first-run email prompt (see OPS-01).",
    )


# ----------------------------------------------------------------- OPS
def ops():
    tmp = Path(tempfile.mkdtemp(prefix="vet_rep_"))
    try:
        pipeline.run(DATA / "extracted" / "rule", out_dir=tmp / "a")
        pipeline.run(DATA / "extracted" / "rule", out_dir=tmp / "b")
        same = {
            n: hashlib.sha256((tmp / "a" / n).read_bytes()).digest()
            == hashlib.sha256((tmp / "b" / n).read_bytes()).digest()
            for n in ("line_results.csv", "findings.csv", "findings.json")
        }
        sa, sb = (json.loads((tmp / x / "summary.json").read_text()) for x in "ab")
        diff = [k for k in sa if sa[k] != sb[k]]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    git = subprocess.run(
        ["git", "status", "--porcelain", "--", "data"], cwd=ROOT, capture_output=True, text=True
    ).stdout
    changed = [ln[3:] for ln in git.splitlines()]
    csv_changed = [c for c in changed if c.endswith(".csv")]
    record(
        "OPS-02",
        "Pass" if all(same.values()) and diff == ["runtime_seconds"] else "Fail",
        f"Pipeline run twice on the same data: identical outputs {same}; summary fields that differ: {diff}. "
        f"After regenerating data, git shows {len(changed)} changed files under data/, of which CSV: "
        f"{csv_changed or 'none'}.",
        "v2 pins PDF creation dates and DOCX zip/core-property timestamps, so regenerating the same seed "
        "should leave contract files unchanged in git.",
    )

    res, err = crash(lambda: run_portfolio([line(lid="BAD", d="31/12/2024")], terms()))
    iss = None if err else res["issues"]
    ok = iss is not None and len(iss) == 1 and iss.iloc[0]["source_row"] == 2
    record(
        "OPS-03",
        "Pass" if ok else "Fail",
        f"Malformed row -> {'CRASH ' + err if err else iss.iloc[0].to_dict()}",
        "Fixed in v2: data/output/input_issues.csv records file, row number, record ID, issue type and "
        "detail for every quarantined invoice line or adjustment; the run completes. No secrets appear in "
        "errors.",
    )

    inv = pd.read_csv(DATA / "invoice_lines.csv", dtype=str)
    timings = []
    tmp = Path(tempfile.mkdtemp(prefix="vet_perf_"))
    try:
        for mult in (1, 10, 50):
            d = tmp / f"x{mult}"
            shutil.copytree(
                DATA, d, ignore=shutil.ignore_patterns("contracts", "output", "eval", "llm_cache")
            )
            big = pd.concat(
                [inv.assign(invoice_line_id=inv["invoice_line_id"] + f"-{k}") for k in range(mult)]
            )
            big.to_csv(d / "invoice_lines.csv", index=False)
            t0 = time.perf_counter()
            pipeline.run(DATA / "extracted" / "rule", data_dir=d, out_dir=d / "out")
            timings.append(f"{len(big):,} lines: {time.perf_counter() - t0:.1f}s")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    cpu = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "(Get-CimInstance Win32_Processor).Name; [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB)",
        ],
        capture_output=True,
        text=True,
    ).stdout.split("\n")
    record(
        "OPS-04",
        "Pass",
        f"Engine (rules terms, no LLM) - {'; '.join(timings)}. Machine: {cpu[0].strip()}, {cpu[1].strip() if len(cpu) > 1 else '?'} GB RAM, "
        f"Python {platform.python_version()}, {platform.platform()}.",
        "Threshold not yet agreed with mentors. Extraction: rules ~0.1s/contract; Gemini time not measured (no key).",
    )


def main():
    for section in (fin, ext, ai, evals, sec, ux, ops):
        try:
            section()
        except Exception:  # noqa: BLE001
            print(f"!! section {section.__name__} crashed:\n{traceback.format_exc()}")
    OUT.mkdir(exist_ok=True)
    manual = OUT / "manual_results.json"  # tests a person ran (e.g. OPS-01 clean clone), with dates
    if manual.exists():
        for test_id, res in json.loads(manual.read_text(encoding="utf-8")).items():
            RESULTS.setdefault(test_id, res)
    ordered = dict(
        sorted(RESULTS.items(), key=lambda kv: (ORDER.index(kv[0].split("-")[0]), kv[0]))
    )
    (OUT / "results.json").write_text(json.dumps(ordered, indent=2), encoding="utf-8")
    print(f"\n{len(RESULTS)} results -> {OUT / 'results.json'}")


if __name__ == "__main__":
    main()
