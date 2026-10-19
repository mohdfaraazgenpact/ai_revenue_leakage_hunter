"""AI Revenue Leakage Hunter - showcase demo.

streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.extract import llm_extractor, rule_extractor  # noqa: E402
from src.extract.document_loader import Page, load_document, segment_clauses  # noqa: E402
from src.extract.run_extraction import read_provenance  # noqa: E402
from src.findings import findings_frame  # noqa: E402
from src.pipeline import run as run_pipeline  # noqa: E402
from src.reconcile import load_terms  # noqa: E402

DATA, REPORTS, OUTPUT = ROOT / "data", ROOT / "reports", ROOT / "data" / "output"
CAUSE_LABEL = {
    "MISSED_ESCALATION": "Missed escalation",
    "PARTIAL_ESCALATION": "Partial escalation",
    "AMENDMENT_NOT_APPLIED": "Amendment not applied",
    "PRICE_BELOW_CONTRACT": "Price below contract",
    "UNSUPPORTED_CREDIT": "Unsupported credit note",
    "OVERBILLING": "Overbilling",
}
ORACLE_SOURCE = "Answer key - engine-only evaluation (not a detector run)"

st.set_page_config(page_title="AI Revenue Leakage Hunter", page_icon=":mag:", layout="wide")
st.markdown(
    """<style>
.block-container {padding-top: 1.6rem;}
div[data-testid="stMetricValue"] {font-size: 1.9rem;}
.quote {background: rgba(255, 196, 0, .18); border-left: 4px solid #f0b400; padding: .55rem .8rem; border-radius: 4px;}
.doc {font-family: Georgia, serif; font-size: .9rem; line-height: 1.5; white-space: pre-wrap; max-height: 420px;
      overflow-y: auto; border: 1px solid rgba(128,128,128,.3); padding: .8rem; border-radius: 6px;}
mark {background: #ffe066; color: #111; padding: 0 2px;}
</style>""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------- data
def usd(x) -> str:
    return f"${Decimal(str(x)):,.0f}"


def available_sources() -> dict[str, Path]:
    src = {}
    for name, label in (
        ("llm", f"{ai_reader()} extraction (AI)"),
        ("rule", "Rules baseline (regex)"),
    ):
        d = DATA / "extracted" / name
        if d.exists() and any(d.glob("*.json")):
            src[label] = d
    src[ORACLE_SOURCE] = DATA / "eval" / "gold"
    return src


@st.cache_data(show_spinner="Hunting for leakage...")
def run_cached(terms_dir: str, use_llm: bool, offline: bool, _stamp: float):
    llm = None
    if use_llm:
        try:
            from src.llm.client import get_client

            llm = get_client(cache_mode="readonly" if offline else None)
        except Exception:
            llm = None
    res = run_pipeline(Path(terms_dir), explain=use_llm, llm=llm)
    return res["summary"], res["lines"], res["findings"], res["issues"]


def llm_status() -> tuple[bool, str]:
    """(live AI call possible, label of the configured model)."""
    from src.llm.client import describe_llm, llm_available

    try:
        return llm_available(), describe_llm()
    except RuntimeError as exc:
        return False, str(exc)


def ai_reader() -> str:
    """Model that produced data/extracted/llm, e.g. 'Claude (claude-sonnet-5-5)'."""
    prov = read_provenance("llm")
    name = {"claude_code": "Claude", "gemini": "Gemini"}.get(prov.get("provider"), "AI")
    return f"{name} ({prov['model']})" if prov.get("model") else name


def contract_path(cid: str) -> Path | None:
    return next((p for p in (DATA / "contracts").glob(f"{cid}.*")), None)


def highlight(text: str, quotes: list[str]) -> str:
    out = html.escape(text)
    for q in quotes:
        if not q:
            continue
        pat = r"\s+".join(re.escape(html.escape(w)) for w in q.split())
        out = re.sub(pat, lambda m: f"<mark>{m.group(0)}</mark>", out, count=1)
    return out


# ---------------------------------------------------------------- sidebar
sources = available_sources()
with st.sidebar:
    st.header("Run settings")
    source_label = st.selectbox("Contract terms from", list(sources), index=0)
    terms_dir = sources[source_label]
    has_key, llm_label = llm_status()
    offline = st.toggle("Offline demo mode (cached AI only)", value=not has_key)
    use_llm = st.toggle("AI narratives", value=has_key or offline)
    if st.button("Re-run hunt", width="stretch"):
        st.cache_data.clear()
    st.caption(f"AI model: {llm_label} - {'available' if has_key else 'not available'}")
    st.divider()
    st.caption(
        "Synthetic contracts and transactions for demonstration only. Findings are candidates for human "
        "review, not validated recoveries. The LLM never computes amounts."
    )

summary, lines, findings, issues = run_cached(str(terms_dir), use_llm, offline, 0.0)
under = [f for f in findings if f.root_cause != "OVERBILLING"]
fdf = findings_frame(findings)
terms = load_terms(terms_dir)

st.title("AI Revenue Leakage Hunter")
st.caption(
    "Contract says → transactions show → AI finds the gap → $ quantified → evidence → human review"
)
if summary["run_mode"] != "detector":
    st.warning(
        "Oracle mode: these results use the answer-key contract terms. They measure the reconciliation "
        "engine only and are not what the detector finds. Choose an extraction source for a detector run."
    )

tabs = st.tabs(
    [
        "Overview",
        "Findings",
        "Contract reader",
        "Jury test",
        "AI vs rules",
        "Value calculator (simulated)",
        "Scorecard",
    ]
)

# ---------------------------------------------------------------- Overview
with tabs[0]:
    billed = Decimal(summary["billed_total"])
    pot = Decimal(summary["potential_underbilling"])
    c = st.columns(5)
    c[0].metric("Potential underbilling (unvalidated)", usd(pot))
    c[1].metric(
        "Illustrative recoverable estimate",
        usd(summary["recoverable_estimate"]),
        help=summary["recoverability_basis"],
    )
    c[2].metric("Findings", summary["findings"])
    c[3].metric("Potential leakage vs billed", f"{(pot / billed * 100):.2f}%" if billed else "-")
    c[4].metric(
        "Lines needing review",
        summary["lines_needing_review"],
        help="Not reconciled: invalid input, currency mismatch, possible duplicate, invoice arithmetic, "
        "adjustment problem or contract terms that could not be determined. See the review queue.",
    )
    st.caption(
        f"{summary['contracts']} contracts · {summary['invoice_lines']:,} invoice lines · "
        f"{usd(billed)} billed · terms source: {source_label} · analysis time "
        f"{summary['runtime_seconds']} s · {summary['duplicate_rows_excluded']} exact duplicate row(s) "
        "excluded. Candidates for human review, not validated recoveries."
    )
    if not fdf.empty:
        u = fdf[fdf["root_cause"] != "OVERBILLING"].copy()
        u["amount"] = u["amount"].astype(float)
        left, right = st.columns(2)
        by_cause = u.groupby("root_cause")["amount"].sum().sort_values()
        left.plotly_chart(
            go.Figure(
                go.Bar(
                    x=by_cause.values,
                    y=[CAUSE_LABEL[i] for i in by_cause.index],
                    orientation="h",
                    marker_color="#2f6fb3",
                )
            ).update_layout(
                title="Leakage by root cause (USD)", height=320, margin=dict(l=10, r=10, t=40, b=10)
            ),
            width="stretch",
        )
        by_cust = u.groupby("customer_name")["amount"].sum().sort_values().tail(8)
        right.plotly_chart(
            go.Figure(
                go.Bar(x=by_cust.values, y=by_cust.index, orientation="h", marker_color="#2f6fb3")
            ).update_layout(
                title="Top customers by leakage (USD)",
                height=320,
                margin=dict(l=10, r=10, t=40, b=10),
            ),
            width="stretch",
        )
        over = fdf[fdf["root_cause"] == "OVERBILLING"]
        if len(over):
            st.info(
                f"Also found {len(over)} overbilling finding(s) worth {usd(over['amount'].astype(float).sum())}. "
                "They are reported separately and never netted against underbilling."
            )

# ---------------------------------------------------------------- Findings
with tabs[1]:
    if fdf.empty:
        st.success("No findings.")
    else:
        view = fdf[
            [
                "finding_id",
                "customer_name",
                "contract_id",
                "sku",
                "root_cause",
                "line_count",
                "amount",
                "recoverable_estimate",
                "extraction_confidence",
                "owner",
            ]
        ].copy()
        view["root_cause"] = view["root_cause"].map(CAUSE_LABEL)
        st.dataframe(
            view,
            hide_index=True,
            width="stretch",
            column_config={
                "amount": st.column_config.NumberColumn("Amount (USD)", format="$%.2f"),
                "recoverable_estimate": st.column_config.NumberColumn(
                    "Illustrative recoverable (USD)", format="$%.2f"
                ),
                "extraction_confidence": st.column_config.ProgressColumn(
                    "Term confidence", min_value=0, max_value=1
                ),
            },
        )
        pick = st.selectbox(
            "Open finding",
            [f"{f.finding_id} · {f.customer_name} · {f.sku} · {usd(f.amount)}" for f in findings],
        )
        f = findings[[x.finding_id for x in findings].index(pick.split(" · ")[0])]
        st.subheader(f.headline)
        st.write(f.narrative)
        st.caption(f"Explanation: {f.explanation_source} · {f.guardrail_note}")

        g = lines[(lines["contract_id"] == f.contract_id) & (lines["sku"] == f.sku)].sort_values(
            "invoice_date"
        )
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=g["invoice_date"],
                y=g["expected_unit_price"].astype(float),
                name="Contract price",
                line=dict(shape="hv", width=3, color="#2f6fb3"),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=g["invoice_date"],
                y=g["invoiced_unit_price"].astype(float),
                name="Billed price",
                line=dict(shape="hv", width=3, dash="dot", color="#d9534f"),
            )
        )
        fig.update_layout(
            title=f"{f.sku}: contract vs billed unit price - the gap is the money",
            height=340,
            margin=dict(l=10, r=10, t=40, b=10),
            yaxis_title="USD per unit",
            legend=dict(orientation="h"),
        )
        st.plotly_chart(fig, width="stretch")

        a, b = st.columns([3, 2])
        with a:
            st.markdown("**Contract evidence**")
            t = terms.get(f.contract_id)
            for kind, ev in f.evidence.items():
                verified = ""
                if t is not None:
                    cit = {
                        "price": t.price_for(f.sku).citation if t.price_for(f.sku) else None,
                        "escalation": t.escalation.citation,
                    }.get(kind)
                    if cit is not None and cit.verified is not None:
                        verified = (
                            " · quote verified ✓" if cit.verified else " · quote NOT verified ✗"
                        )
                st.markdown(
                    f"{kind.title()} — clause **{ev['clause_id']}**, page {ev['page']}{verified}"
                )
                st.markdown(
                    f"<div class='quote'>{html.escape(str(ev['quote']))}</div>",
                    unsafe_allow_html=True,
                )
            st.markdown(f"**Calculation:** `{f.calculation_latest}`")
        with b:
            st.markdown(f"**Suggested owner:** {f.owner}")
            st.markdown(f"**Recommended action:** {f.recommended_action}")
            st.text_area("Draft rebilling review note (internal)", f.rebill_note, height=260)
        st.markdown("**Affected invoice lines**")
        ids = set(f.invoice_line_ids)
        st.dataframe(
            lines[lines["invoice_line_id"].isin(ids)][
                [
                    "invoice_line_id",
                    "invoice_id",
                    "invoice_date",
                    "quantity",
                    "invoiced_unit_price",
                    "expected_unit_price",
                    "net_billed_amount",
                    "expected_line_amount",
                    "potential_underbilling",
                    "potential_overbilling",
                ]
            ],
            hide_index=True,
            width="stretch",
            height=220,
        )

        st.markdown("**Review decision** (a human approves every action)")
        r1, r2, r3 = st.columns([1, 2, 1])
        reviewer = r1.text_input("Reviewer", value="Demo reviewer")
        reason = r2.text_input("Reason / comment")
        decision = r3.radio("Decision", ["Approve rebill review", "Reject"], horizontal=False)
        if st.button("Record decision", type="primary"):
            log = OUTPUT / "review_decisions.csv"
            row = pd.DataFrame(
                [
                    {
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                        "finding_id": f.finding_id,
                        "contract_id": f.contract_id,
                        "sku": f.sku,
                        "amount": str(f.amount),
                        "decision": decision,
                        "reviewer": reviewer,
                        "reason": reason,
                    }
                ]
            )
            row.to_csv(log, mode="a", header=not log.exists(), index=False)
            st.success(
                f"Recorded: {decision} for {f.finding_id}. Audit log: data/output/review_decisions.csv"
            )

    st.divider()
    st.markdown("**Export** (same run and terms source as shown above)")
    d1, d2, d3 = st.columns(3)
    d1.download_button(
        "Download findings (CSV)",
        fdf.to_csv(index=False).encode("utf-8"),
        file_name="findings.csv",
        mime="text/csv",
        disabled=fdf.empty,
    )
    d2.download_button(
        "Download line results (CSV)",
        lines.to_csv(index=False).encode("utf-8"),
        file_name="line_results.csv",
        mime="text/csv",
    )
    d3.download_button(
        "Download input issues (CSV)",
        issues.to_csv(index=False).encode("utf-8"),
        file_name="input_issues.csv",
        mime="text/csv",
    )
    review = lines[lines["status"].isin(["REVIEW", "DUPLICATE"])]
    with st.expander(f"Review queue: {len(review)} line(s) not reconciled", expanded=False):
        st.caption(
            "These lines are never counted as matches or leakage. Each needs a person to fix the input "
            "or confirm the contract terms."
        )
        if not review.empty:
            st.dataframe(
                review[
                    [
                        "invoice_line_id",
                        "source_row",
                        "contract_id",
                        "sku",
                        "invoice_date",
                        "status",
                        "issue_type",
                        "reason",
                    ]
                ],
                hide_index=True,
                width="stretch",
                height=260,
            )

# ---------------------------------------------------------------- Contract reader
with tabs[2]:
    cids = sorted(terms)
    cid = st.selectbox("Contract", cids, key="reader_cid")
    t = terms[cid]
    path = contract_path(cid)
    left, right = st.columns([2, 3])
    with left:
        st.markdown(
            f"**{t.customer_name}** · {t.effective_date} → {t.end_date} · source: `{t.source}`"
        )
        rows = [
            {
                "Term": f"Price {p.sku}",
                "Value": f"USD {p.unit_price:,.2f}",
                "Clause": p.citation.clause_id if p.citation else "",
                "Verified": (p.citation.verified if p.citation else None),
            }
            for p in t.prices
        ]
        e = t.escalation
        val = {
            "none": "No escalation",
            "fixed_pct": f"{e.rate_pct}% annually from {e.first_escalation_date}",
            "cpi": f"CPI, floor {e.floor_pct}% / cap {e.cap_pct}% from {e.first_escalation_date}",
        }[e.type]
        rows.append(
            {
                "Term": "Escalation",
                "Value": val,
                "Clause": e.citation.clause_id if e.citation else "",
                "Verified": e.citation.verified if e.citation else None,
            }
        )
        rows += [
            {
                "Term": f"Amendment {a.amendment_id}",
                "Value": f"{a.sku}: USD {a.new_unit_price} from {a.effective_date}",
                "Clause": a.citation.clause_id if a.citation else "",
                "Verified": a.citation.verified if a.citation else None,
            }
            for a in t.amendments
        ]
        rows += [
            {
                "Term": "Approved discount",
                "Value": f"{d.sku}: {d.discount_pct}% {d.start_date} → {d.end_date}",
                "Clause": d.citation.clause_id if d.citation else "",
                "Verified": d.citation.verified if d.citation else None,
            }
            for d in t.approved_discounts
        ]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        if t.field_confidence:
            st.caption(
                "Confidence: " + ", ".join(f"{k} {v:.2f}" for k, v in t.field_confidence.items())
            )
    with right:
        if path:
            pages = load_document(path)
            quotes = (
                [p.citation.quote for p in t.prices if p.citation]
                + ([e.citation.quote] if e.citation else [])
                + [a.citation.quote for a in t.amendments if a.citation]
                + [d.citation.quote for d in t.approved_discounts if d.citation]
            )
            pg = st.radio("Page", [p.page for p in pages], horizontal=True)
            page = next(p for p in pages if p.page == pg)
            st.markdown(
                f"<div class='doc'>{highlight(page.text, quotes)}</div>", unsafe_allow_html=True
            )
            st.download_button("Download contract", path.read_bytes(), file_name=path.name)

# ---------------------------------------------------------------- Jury test
with tabs[3]:
    st.markdown(
        "**Change the contract, and watch the money change.** Edit the price-escalation wording of any "
        "contract (for example change the rate or write it in words), then re-read it with AI."
    )
    cid = st.selectbox("Contract", sorted(terms), key="jury_cid")
    path = contract_path(cid)
    pages = load_document(path)
    t = terms[cid]
    current = t.escalation.citation.quote if t.escalation.citation else ""
    if not current:
        ch = next((c for c in segment_clauses(pages) if c.clause_id == "4.2"), None)
        current = ch.text if ch else ""
    edited = st.text_area("Escalation clause", value=current, height=110, key=f"jury_text_{cid}")
    live = has_key and not offline
    st.caption(
        "Reader: "
        + (
            f"{llm_label} (live call)"
            if live
            else "rules baseline - configure LLM_PROVIDER in .env and turn off offline mode for AI"
        )
    )
    if st.button("Re-read contract and re-run hunt", type="primary"):
        pat = r"\s+".join(re.escape(w) for w in current.split())
        new_pages, replaced = [], False
        for p in pages:
            txt, n = (
                re.subn(pat, edited.replace("\\", "\\\\"), p.text, count=1)
                if (current and not replaced)
                else (p.text, 0)
            )
            replaced = replaced or n > 0
            new_pages.append(Page(p.page, txt))
        if not replaced:
            st.error("Could not locate the original clause in the document text.")
        else:
            with st.spinner("Reading the edited contract..."):
                if live:
                    from src.llm.client import get_client

                    new_terms, issues = llm_extractor.extract(
                        path, get_client(), contract_id=cid, pages=new_pages
                    )
                else:
                    new_terms, issues = (
                        rule_extractor.extract(path, contract_id=cid, pages=new_pages),
                        [],
                    )
                before = sum((x.amount for x in under if x.contract_id == cid), Decimal("0"))
                trial = dict(terms)
                trial[cid] = new_terms
                res = run_pipeline(
                    terms=trial, terms_dir=terms_dir, out_dir=OUTPUT / "jury_test", explain=False
                )
                after = sum(
                    (
                        x.amount
                        for x in res["findings"]
                        if x.contract_id == cid and x.root_cause != "OVERBILLING"
                    ),
                    Decimal("0"),
                )
            e = new_terms.escalation
            c1, c2, c3 = st.columns(3)
            c1.metric("Leakage before edit", usd(before))
            c2.metric("Leakage after edit", usd(after), delta=f"{usd(after - before)}")
            c3.metric(
                "Escalation now read as",
                {"none": "none", "fixed_pct": f"{e.rate_pct}%", "cpi": "CPI"}[e.type],
                help=f"First escalation: {e.first_escalation_date}",
            )
            if issues:
                st.warning(
                    f"{len(issues)} item(s) sent to review: "
                    + "; ".join(i["issue"] for i in issues)
                )

# ---------------------------------------------------------------- AI vs rules
with tabs[4]:
    st.markdown(
        "**Why AI?** The same obligation is written many ways. Rules handle the standard phrasing and miss the rest. "
        "Small reading errors become large money errors."
    )
    ext = REPORTS / "extraction_summary.json"
    if ext.exists():
        summ = json.loads(ext.read_text())
        rows = []
        for s in summ:
            ev_path = REPORTS / f"evaluation_{s['extractor']}.json"
            ev = json.loads(ev_path.read_text()) if ev_path.exists() else {}
            rows.append(
                {
                    "Reader": {"llm": f"{ai_reader()} (AI)", "rule": "Rules (regex)"}.get(
                        s["extractor"], s["extractor"]
                    ),
                    "Field accuracy": f"{s['key_field_accuracy']:.1%}",
                    "Contracts read fully correctly": f"{s['contracts_all_correct']}/{s['contracts_total']}",
                    "Leakage lines found": f"{ev.get('line_recall', 0):.0%}" if ev else "-",
                    "Leakage $ found": usd(ev["detected_usd"]) if ev else "-",
                    "False overbilling $": usd(
                        Decimal(ev["overbilling_detected_usd"])
                        - Decimal(ev["overbilling_seeded_usd"])
                    )
                    if ev
                    else "-",
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        variants = sorted({v for s in summ for v in s["escalation_by_wording"]})
        st.markdown("**Escalation clause read correctly, by wording style**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Wording": v,
                        **{s["extractor"]: s["escalation_by_wording"].get(v, "-") for s in summ},
                    }
                    for v in variants
                ]
            ),
            hide_index=True,
            width="stretch",
        )
    else:
        st.info(
            "Run `python -m src.extract.run_extraction --extractor both` then `python -m src.evaluate_extraction`."
        )

# ---------------------------------------------------------------- Value calculator
with tabs[5]:
    billed = Decimal(summary["billed_total"])
    measured = float(Decimal(summary["potential_underbilling"]) / billed * 100) if billed else 1.0
    c1, c2, c3, c4 = st.columns(4)
    revenue = c1.number_input("Client annual revenue (USD M)", 100, 50000, 1000, step=100)
    rate = c2.slider(
        "Leakage rate (%)",
        0.1,
        3.0,
        round(measured, 2),
        0.05,
        help="Default = rate measured in this PoC run",
    )
    recovery = c3.slider("Recovery rate (%)", 10, 100, 60, 5)
    fee = c4.slider("Outcome-based fee (% of recovered)", 5, 40, 20, 1)
    leak = revenue * 1e6 * rate / 100
    rec = leak * recovery / 100
    k = st.columns(3)
    k[0].metric("Annual leakage", f"${leak / 1e6:,.1f}M")
    k[1].metric("Illustrative recovery (simulated)", f"${rec / 1e6:,.1f}M")
    k[2].metric("Illustrative fee (simulated)", f"${rec * fee / 100 / 1e6:,.1f}M")
    st.info(
        "Simulation from your inputs, not a result of this PoC. Nothing has been recovered. The real "
        "leakage rate is established in a client diagnostic. Every 1% of USD 1B revenue is USD 10M."
    )

# ---------------------------------------------------------------- Scorecard
with tabs[6]:
    st.markdown(
        "**Measured against seeded ground truth** (synthetic data; real-client accuracy is established in a pilot)"
    )
    for p in sorted(REPORTS.glob("evaluation_*.json")):
        ev = json.loads(p.read_text())
        with st.expander(
            f"{ev['label']}{' (answer key, engine-only)' if ev['label'] == 'gold' else ''} · gate {'PASS' if not ev['gate_failures'] else 'FAIL'}",
            expanded=ev["label"] != "gold",
        ):
            m = st.columns(5)
            m[0].metric("Recall (lines)", f"{ev['line_recall']:.1%}")
            m[1].metric("Precision (lines)", f"{ev['line_precision']:.1%}")
            m[2].metric("$ error", f"{ev['dollar_error_pct']}%")
            m[3].metric("False positives on traps", ev["trap_false_positive_lines"])
            m[4].metric("Root-cause accuracy", f"{ev.get('root_cause_accuracy', 0):.0%}")
            if ev["gate_failures"]:
                st.warning("; ".join(ev["gate_failures"]))
            st.dataframe(pd.DataFrame(ev["per_scenario"]), hide_index=True, width="stretch")
