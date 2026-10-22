"""AI Revenue Leakage Hunter - showcase demo.

streamlit run app/streamlit_app.py

Business journey first (Home, Leakage Analysis, Review Queue, Business Impact); the technical pages
(End-to-End Flow, Technical Architecture) show why the results can be trusted.
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
DECISION_LOG = OUTPUT / "review_decisions.csv"
ARCH_DOC = ROOT / "docs" / "technical_architecture.md"
REPO_URL = "https://github.com/mohdfaraazgenpact/ai_revenue_leakage_hunter"
CAUSE_LABEL = {
    "MISSED_ESCALATION": "Missed escalation",
    "PARTIAL_ESCALATION": "Partial escalation",
    "AMENDMENT_NOT_APPLIED": "Amendment not applied",
    "PRICE_BELOW_CONTRACT": "Price below contract",
    "UNSUPPORTED_CREDIT": "Unsupported credit note",
    "OVERBILLING": "Overbilling",
}
ORACLE_SOURCE = "Answer key - engine-only evaluation (not a detector run)"
# Review outcomes follow the end-to-end flow: "Recovery action justified?" Yes / No / unresolved.
VALIDATED, UNRESOLVED, CLOSED = (
    "Validated - recovery justified",
    "Unresolved - needs investigation",
    "Closed - no recovery",
)
DISCLAIMER = "Prototype using synthetic data. Findings are potential discrepancies, not confirmed recoveries."

st.set_page_config(page_title="AI Revenue Leakage Hunter", page_icon=":mag:", layout="wide")
st.markdown(
    """<style>
.block-container {padding-top: 1.6rem;}
div[data-testid="stMetricValue"] {font-size: 1.9rem;}
.quote {background: rgba(255, 196, 0, .18); border-left: 4px solid #f0b400; padding: .55rem .8rem; border-radius: 4px;}
.doc {font-family: Georgia, serif; font-size: .9rem; line-height: 1.5; white-space: pre-wrap; max-height: 420px;
      overflow-y: auto; border: 1px solid rgba(128,128,128,.3); padding: .8rem; border-radius: 6px;}
mark {background: #ffe066; color: #111; padding: 0 2px;}
.hero {background: #13304a; color: #fff; border-radius: 12px; padding: 1.4rem 1.6rem 1.5rem; margin-bottom: 1rem;}
.hero .brand {font-weight: 700; font-size: 1.05rem;}
.hero .kicker {font-size: .75rem; letter-spacing: .06em; opacity: .8; text-transform: uppercase;}
.hero hr {border: 0; border-top: 1px solid rgba(255,255,255,.2); margin: .9rem 0;}
.hero h1 {color: #fff; font-size: 2rem; margin: 0 0 .4rem; padding: 0;}
.hero p {font-size: 1.05rem; opacity: .92; margin: 0 0 .9rem;}
.chip {display: inline-block; background: #1f6f78; color: #fff; font-weight: 600; font-size: .85rem;
       border-radius: 6px; padding: .35rem .7rem; margin: 0 .4rem .4rem 0;}
.aud {display: inline-block; border: 1px solid rgba(128,128,128,.35); border-radius: 6px; padding: .3rem .7rem;
      margin: 0 .4rem .4rem 0; font-size: .9rem;}
.opp {border: 1px solid rgba(128,128,128,.3); border-radius: 10px; padding: 1rem 1.2rem;}
.opp .tag {font-size: .78rem; letter-spacing: .04em; opacity: .75;}
.opp .big {font-size: 2rem; font-weight: 700; color: #1e9e4a;}
</style>""",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------- helpers
def usd(x) -> str:
    return f"${Decimal(str(x)):,.0f}"


def money_short(x: float) -> str:
    return f"${x / 1e9:,.1f} billion" if x >= 1e9 else f"${x / 1e6:,.1f} million"


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


def finding_key(contract_id: str, sku: str, root_cause: str) -> str:
    """Finding IDs are positional per run, so decisions are keyed on what the finding is about."""
    return f"{contract_id}|{sku}|{root_cause}"


def latest_decisions() -> dict[str, dict]:
    """Latest review decision per finding key from the audit log (later rows win)."""
    if not DECISION_LOG.exists():
        return {}
    log = pd.read_csv(DECISION_LOG, dtype=str).fillna("")
    if "root_cause" not in log.columns:  # rows written before decisions were keyed by root cause
        return {}
    return {
        finding_key(r.contract_id, r.sku, r.root_cause): r._asdict()
        for r in log.itertuples(index=False)
    }


def review_status(f, decisions: dict[str, dict]) -> str:
    d = decisions.get(finding_key(f.contract_id, f.sku, f.root_cause))
    return d["decision"] if d else "Awaiting review"


def finding_label(f) -> str:
    return f"{f.finding_id} · {f.customer_name} · {f.sku} · {CAUSE_LABEL[f.root_cause]} · {usd(f.amount)}"


# ---------------------------------------------------------------- shared run (sidebar)
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


def oracle_banner() -> None:
    if summary["run_mode"] != "detector":
        st.warning(
            "Oracle mode: these results use the answer-key contract terms. They measure the reconciliation "
            "engine only and are not what the detector finds. Choose an extraction source for a detector run."
        )


# ---------------------------------------------------------------- Home
def page_home() -> None:
    st.markdown(
        """<div class="hero">
<div class="brand">🏛️ AI Revenue Leakage Hunter</div>
<div class="kicker">Intelligent O2C revenue assurance</div>
<hr/>
<h1>Recover the revenue you've already earned.</h1>
<p>Identify contract-to-invoice discrepancies, prioritise investigation, and help Finance teams turn missed
billing opportunities into validated recovery actions.</p>
<span class="chip">Contract-to-cash visibility</span><span class="chip">Evidence-backed findings</span><span
class="chip">Human-validated recovery</span>
</div>""",
        unsafe_allow_html=True,
    )

    # Illustrative opportunity model directly under the headline.
    st.markdown("##### Illustrative opportunity model — not a validated result")
    a, x, b, eq, r = st.columns([3, 0.4, 3, 0.4, 4], vertical_alignment="center")
    billings = a.number_input(
        "Addressable annual billings (USD billion)", 0.1, 100.0, 1.0, step=0.1, format="%.1f"
    )
    x.markdown("### ×")
    rate = b.number_input(
        "Assumed leakage rate (%)",
        0.1,
        5.0,
        1.0,
        step=0.1,
        format="%.1f",
        help="A conservative planning assumption for a price-leakage use case, not a measured industry "
        "rate. See 'Sources and caveats' below.",
    )
    eq.markdown("### =")
    opportunity = billings * 1e9 * rate / 100
    r.markdown(
        f"""<div class="opp"><div class="tag">POTENTIAL GROSS LEAKAGE OPPORTUNITY</div>
<div class="big">{money_short(opportunity)}</div></div>""",
        unsafe_allow_html=True,
    )
    st.caption(
        "Illustrative opportunity: 1% of addressable annual billings. This is a conservative planning "
        "assumption, not a measured industry rate or validated recovery forecast. Published leakage estimates "
        "are higher but use broader scopes and different measurement bases."
    )
    with st.expander("Sources and caveats"):
        st.markdown(
            "- [MGI Research, *Revenue Leakage Series Part 1* (Dec 2025)]"
            "(https://mgiresearch.com/research/revenue-leakage/): revenue leakage of at least 3-5% of revenue. "
            "No sample size or method is published.\n"
            "- [WorldCC, *Contract Management: An Overlooked Driver of Business Agility and Financial "
            "Performance* (Aug 2025)](https://www.cfo.com/press-release/20250819-the-multi-million-dollar-leak-"
            "in-your-contracts-and-how-to-stop-it/): almost 9% of annual revenue lost through poor contract "
            "management, a broader measure than billing leakage.\n"
            "- [WorldCC with Deloitte, *The ROI of Contracting Excellence* (2023)]"
            "(https://news.worldcc.com/news-from-worldcc/are-organizations-unlocking-their-full-financial-"
            "potential): average erosion of 8.6% of contract value, not revenue.\n\n"
            "These studies use broader definitions and different measurement bases, so they are context, not "
            "direct benchmarks for this price-leakage use case. A lower rate is not automatically conservative "
            "for every client: the 1% must be tested against the client's addressable billings and validated "
            "price leakage in a controlled pilot. The actual opportunity also depends on contractual "
            "enforceability, customer disputes, recoverability and collection outcomes."
        )

    st.subheader("Potential business value")
    st.caption(
        "Illustrative opportunity sizing — replace with pilot-validated figures when available."
    )
    cards = [
        (
            ":material/search:",
            "Leakage identified",
            "Find potential underbilling and missed contractual entitlements.",
        ),
        (
            ":material/account_balance_wallet:",
            "Cash inflow supported",
            "Prioritise validated corrections, rebilling and recovery follow-up.",
        ),
        (
            ":material/schedule:",
            "Less manual effort",
            "Reduce time spent reconciling contracts, orders and invoices.",
        ),
        (
            ":material/verified_user:",
            "Controlled decisions",
            "Maintain evidence, review exceptions and audit financial decisions.",
        ),
    ]
    for row in (cards[:2], cards[2:]):
        for col, (icon, title, text) in zip(st.columns(2), row, strict=True):
            with col.container(border=True):
                st.markdown(f"{icon} **{title}**")
                st.caption(text)

    st.subheader("Built for the people who protect revenue")
    st.markdown(
        "".join(
            f'<span class="aud">{a}</span>'
            for a in (
                "O2C leaders",
                "Finance controllers",
                "Revenue assurance",
                "AR & billing teams",
                "Transformation leaders",
            )
        ),
        unsafe_allow_html=True,
    )

    st.subheader("How it works")
    steps = st.columns(4)
    for col, (n, title, text) in zip(
        steps,
        [
            (
                "1",
                "Read the contract",
                "AI extracts prices, escalations and amendments, quoting the clause.",
            ),
            (
                "2",
                "Calculate the gap",
                "Deterministic logic compares what should have been billed with what was.",
            ),
            (
                "3",
                "Prioritise findings",
                "Each discrepancy comes with evidence, an owner and an action.",
            ),
            (
                "4",
                "Validate and act",
                "Finance confirms, investigates or closes each case before recovery.",
            ),
        ],
        strict=True,
    ):
        with col.container(border=True):
            st.markdown(f"**{n}. {title}**")
            st.caption(text)
    st.caption(
        "AI interprets contract language, deterministic logic calculates the money, and Finance validates "
        "recovery decisions."
    )

    st.subheader("In this prototype run (synthetic data)")
    m = st.columns(3)
    m[0].metric("Potential leakage detected", usd(summary["potential_underbilling"]))
    m[1].metric("Findings to review", len(findings))
    m[2].metric("Contracts analysed", summary["contracts"])
    oracle_banner()

    st.divider()
    l1, l2, l3, l4 = st.columns(4)
    l1.page_link(
        PAGES["analysis"], label="Start: Leakage Analysis", icon=":material/arrow_forward:"
    )
    l2.page_link(PAGES["flow"], label="End-to-end business flow", icon=":material/account_tree:")
    l3.page_link(PAGES["arch"], label="Technical architecture", icon=":material/architecture:")
    l4.link_button("GitHub repository", REPO_URL, icon=":material/code:")
    st.caption(DISCLAIMER)


# ---------------------------------------------------------------- Leakage Analysis
def show_finding(f) -> None:
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
                    verified = " · quote verified ✓" if cit.verified else " · quote NOT verified ✗"
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


def page_analysis() -> None:
    st.title("Leakage Analysis")
    st.caption(
        "Contract says → invoices show → the gap is quantified → evidence attached → Finance reviews"
    )
    oracle_banner()
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
        "adjustment problem or contract terms that could not be determined. See the Review Queue.",
    )
    st.caption(
        f"{summary['contracts']} contracts · {summary['invoice_lines']:,} invoice lines · "
        f"{usd(billed)} billed · terms source: {source_label} · analysis time "
        f"{summary['runtime_seconds']} s · {summary['duplicate_rows_excluded']} exact duplicate row(s) "
        "excluded. Candidates for human review, not validated recoveries."
    )

    tabs = st.tabs(["Prioritised findings", "Contract evidence", "What-if: change a contract"])
    with tabs[0]:
        findings_tab()
    with tabs[1]:
        contract_tab()
    with tabs[2]:
        whatif_tab()


def findings_tab() -> None:
    if fdf.empty:
        st.success("No findings.")
        return
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

    decisions = latest_decisions()
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
    view["review_status"] = [review_status(f, decisions) for f in findings]
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
            "review_status": "Review status",
        },
    )
    pick = st.selectbox("Open finding", [finding_label(f) for f in findings], key="analysis_pick")
    show_finding(findings[[finding_label(f) for f in findings].index(pick)])
    st.page_link(
        PAGES["review"],
        label="Validate this finding in the Review Queue",
        icon=":material/fact_check:",
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


def contract_tab() -> None:
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


def whatif_tab() -> None:
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

                    new_terms, new_issues = llm_extractor.extract(
                        path, get_client(), contract_id=cid, pages=new_pages
                    )
                else:
                    new_terms, new_issues = (
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
            held = res["lines"]
            held = held[(held["contract_id"] == cid) & (held["status"] == "REVIEW")]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Leakage before edit", usd(before))
            c2.metric("Leakage after edit", usd(after), delta=f"{usd(after - before)}")
            c4.metric(
                "Lines sent to review",
                len(held),
                help="Lines the engine could not price safely with the edited terms. They are held for a "
                "person to check, not counted as matches or leakage.",
            )
            c3.metric(
                "Escalation now read as",
                {"none": "none", "fixed_pct": f"{e.rate_pct}%", "cpi": "CPI"}[e.type],
                help=f"First escalation: {e.first_escalation_date}",
            )
            if new_issues:
                st.warning(
                    f"{len(new_issues)} item(s) sent to review: "
                    + "; ".join(i["issue"] for i in new_issues)
                )


# ---------------------------------------------------------------- Review Queue
def page_review() -> None:
    st.title("Review Queue")
    st.caption(
        "Finance validates every finding before any recovery action. Decisions are written to an audit log."
    )
    oracle_banner()
    flash = st.session_state.pop("review_flash", None)
    if flash:
        st.success(flash)

    decisions = latest_decisions()
    statuses = [review_status(f, decisions) for f in findings]
    c = st.columns(4)
    c[0].metric("Awaiting review", statuses.count("Awaiting review"))
    c[1].metric("Validated", statuses.count(VALIDATED))
    c[2].metric("Unresolved", statuses.count(UNRESOLVED))
    c[3].metric("Closed", statuses.count(CLOSED))

    tabs = st.tabs(
        [
            f"Findings to validate ({len(findings)})",
            f"Data exceptions ({summary['lines_needing_review']})",
            "Decision audit log",
        ]
    )
    with tabs[0]:
        if not findings:
            st.success("No findings.")
        else:
            only_open = st.toggle("Show only findings awaiting review", value=False)
            queue = [
                f
                for f, s in zip(findings, statuses, strict=True)
                if not only_open or s == "Awaiting review"
            ]
            if not queue:
                st.success("Every finding has a decision.")
            else:
                pick = st.selectbox("Finding", [finding_label(f) for f in queue], key="review_pick")
                f = queue[[finding_label(x) for x in queue].index(pick)]
                st.markdown(f"**{f.headline}**")
                k = st.columns(4)
                k[0].metric("Amount", usd(f.amount))
                k[1].metric("Root cause", CAUSE_LABEL[f.root_cause])
                k[2].metric("Invoice lines", f.line_count)
                k[3].metric("Current status", review_status(f, decisions))
                for kind, ev in f.evidence.items():
                    st.markdown(f"{kind.title()} — clause **{ev['clause_id']}**, page {ev['page']}")
                    st.markdown(
                        f"<div class='quote'>{html.escape(str(ev['quote']))}</div>",
                        unsafe_allow_html=True,
                    )
                st.markdown(f"**Calculation:** `{f.calculation_latest}`")
                st.markdown(
                    f"**Suggested owner:** {f.owner} · **Recommended action:** {f.recommended_action}"
                )
                with st.expander("Full finding detail"):
                    show_finding(f)

                st.markdown("**Is a recovery action justified?** (a human approves every action)")
                r1, r2, r3 = st.columns([1, 2, 1.4])
                reviewer = r1.text_input("Reviewer", value="Demo reviewer")
                reason = r2.text_input("Reason / comment")
                decision = r3.radio("Decision", [VALIDATED, UNRESOLVED, CLOSED])
                if st.button("Record decision", type="primary"):
                    row = pd.DataFrame(
                        [
                            {
                                "timestamp": datetime.now().isoformat(timespec="seconds"),
                                "finding_id": f.finding_id,
                                "contract_id": f.contract_id,
                                "sku": f.sku,
                                "root_cause": f.root_cause,
                                "amount": str(f.amount),
                                "decision": decision,
                                "reviewer": reviewer,
                                "reason": reason,
                            }
                        ]
                    )
                    OUTPUT.mkdir(parents=True, exist_ok=True)
                    row.to_csv(
                        DECISION_LOG, mode="a", header=not DECISION_LOG.exists(), index=False
                    )
                    st.session_state["review_flash"] = (
                        f"Recorded: {decision} for {f.finding_id}. Audit log: data/output/review_decisions.csv"
                    )
                    st.rerun()
    with tabs[1]:
        review = lines[lines["status"].isin(["REVIEW", "DUPLICATE"])]
        st.caption(
            "These invoice lines are never counted as matches or leakage. Each needs a person to fix the input "
            "or confirm the contract terms."
        )
        if review.empty:
            st.success("No data exceptions.")
        else:
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
    with tabs[2]:
        if DECISION_LOG.exists():
            st.dataframe(pd.read_csv(DECISION_LOG, dtype=str), hide_index=True, width="stretch")
        else:
            st.info("No decisions recorded yet.")


# ---------------------------------------------------------------- Business Impact
def page_impact() -> None:
    st.title("Business Impact")
    st.caption(
        "Detected leakage is not recovered cash. The three measures below are kept separate and never added "
        "together."
    )
    oracle_banner()
    decisions = latest_decisions()
    detected = sum((f.amount for f in under), Decimal("0"))
    validated = [f for f in under if review_status(f, decisions) == VALIDATED]
    validated_usd = sum((f.amount for f in validated), Decimal("0"))
    reviewed = [f for f in under if review_status(f, decisions) != "Awaiting review"]

    c = st.columns(3)
    with c[0].container(border=True):
        st.markdown(":material/search: **1. Potential leakage detected**")
        st.metric("Discrepancy value identified by the engine", usd(detected))
        st.caption(f"{len(under)} underbilling findings · synthetic data · available now")
    with c[1].container(border=True):
        st.markdown(":material/fact_check: **2. Validated recovery opportunity**")
        st.metric("Confirmed by Finance after checking evidence and terms", usd(validated_usd))
        st.caption(
            f"{len(validated)} validated of {len(reviewed)} reviewed · from Review Queue decisions "
            "(synthetic walkthrough)"
        )
    with c[2].container(border=True):
        st.markdown(":material/payments: **3. Cash actually recovered**")
        st.metric("Received and reconciled against the receivable", "Requires pilot")
        st.caption("Not measurable in the PoC: needs billing correction and cash-receipt tracking.")

    if detected:
        fig = go.Figure(
            go.Bar(
                x=[float(detected), float(validated_usd)],
                y=["Detected", "Validated"],
                orientation="h",
                marker_color=["#2f6fb3", "#1e9e4a"],
                text=[usd(detected), usd(validated_usd)],
                textposition="auto",
            )
        ).update_layout(
            title="From detected to validated (USD, synthetic)",
            height=220,
            margin=dict(l=10, r=10, t=40, b=10),
            yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(fig, width="stretch")
    over = [f for f in findings if f.root_cause == "OVERBILLING"]
    if over:
        st.info(
            f"{len(over)} overbilling finding(s) worth {usd(sum((f.amount for f in over), Decimal('0')))} "
            "are customer credits to review, reported separately and never netted against underbilling."
        )

    st.subheader("Scenario calculator (simulated)")
    billed = Decimal(summary["billed_total"])
    measured = float(Decimal(summary["potential_underbilling"]) / billed * 100) if billed else 1.0
    c1, c2, c3, c4 = st.columns(4)
    revenue = c1.number_input("Client annual billings (USD M)", 100, 50000, 1000, step=100)
    rate = c2.slider(
        "Leakage rate (%)",
        0.1,
        3.0,
        round(measured, 2),
        0.05,
        help="Default = rate measured in this synthetic PoC run",
    )
    recovery = c3.slider("Recovery rate (%)", 10, 100, 60, 5)
    fee = c4.slider("Outcome-based fee (% of recovered)", 5, 40, 20, 1)
    leak = revenue * 1e6 * rate / 100
    rec = leak * recovery / 100
    k = st.columns(3)
    k[0].metric("Annual leakage (simulated)", f"${leak / 1e6:,.1f}M")
    k[1].metric("Illustrative recovery (simulated)", f"${rec / 1e6:,.1f}M")
    k[2].metric("Illustrative fee (simulated)", f"${rec * fee / 100 / 1e6:,.1f}M")
    st.info(
        "Simulation from your inputs, not a result of this PoC. Nothing has been recovered. The real "
        "leakage rate is established in a client diagnostic. Every 1% of USD 1B billings is USD 10M."
    )


# ---------------------------------------------------------------- End-to-End Flow
FLOW_DOT = """digraph G {
  rankdir=TB; bgcolor="transparent"; nodesep=0.35; ranksep=0.35;
  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, color="#9bb7d4",
        fillcolor="#e5f3ff", fontcolor="#0b3d6e", width=2.6];
  edge [color="#8f8f8f", fontname="Helvetica", fontsize=10, fontcolor="#0b3d6e"];
  a [label="Contract terms and amendments"]; b [label="Orders and usage"];
  c [label="Invoices, credits and payments"];
  d [label="Ingest and validate data"]; e [label="AI extracts contractual terms"];
  f [label="Verify quoted evidence\\nand required fields"];
  g [label="Terms and data reliable?", shape=diamond, fillcolor="#f5faff", style="filled,dashed", width=2.2];
  h [label="Human review queue"]; i [label="Deterministic financial calculation"];
  j [label="Compare expected vs billed"]; k [label="Prioritised potential\\nleakage findings"];
  l [label="Finance validates discrepancy"];
  m [label="Recovery action justified?", shape=diamond, fillcolor="#f5faff", style="filled,dashed", width=2.2];
  n [label="Resolve, dispute or close case"];
  o [label="Correct billing or\\ninitiate recovery", fillcolor="#f2f2f2", fontcolor="#555555", style="rounded,filled,dashed"];
  p [label="Track invoice, receivable\\nand cash receipt", fillcolor="#f2f2f2", fontcolor="#555555", style="rounded,filled,dashed"];
  q [label="Measure validated value\\nand cash recovered", fillcolor="#f2f2f2", fontcolor="#555555", style="rounded,filled,dashed"];
  {rank=same; a; b; c}
  a -> d; b -> d; c -> d; d -> e -> f -> g;
  g -> h [label=" No"]; g -> i [label=" Yes"];
  i -> j -> k -> l; h -> l; l -> m;
  m -> n [label=" No / unresolved"]; m -> o [label=" Yes"]; o -> p -> q;
}"""


def page_flow() -> None:
    st.title("End-to-End Business Flow")
    st.markdown(
        "How a contract discrepancy becomes a validated recovery action. **AI interprets contract language, "
        "deterministic logic calculates the money, and Finance validates recovery decisions.**"
    )
    left, right = st.columns([3, 2])
    with left:
        st.graphviz_chart(FLOW_DOT, width="stretch")
        st.caption("Blue boxes: built in the PoC. Grey dashed boxes: future / pilot scope.")
    with right:
        st.markdown("**Where each step lives**")
        st.dataframe(
            pd.DataFrame(
                [
                    (
                        "Contract terms, orders/usage, invoices, credits",
                        "Built (synthetic data)",
                        "Leakage Analysis",
                    ),
                    ("Ingest and validate data", "Built", "Review Queue → Data exceptions"),
                    (
                        "AI extracts contractual terms",
                        "Built",
                        "Leakage Analysis → Contract evidence",
                    ),
                    (
                        "Verify quoted evidence and required fields",
                        "Built",
                        "Contract evidence (✓ / ✗)",
                    ),
                    ("Human review queue", "Built", "Review Queue"),
                    ("Deterministic financial calculation", "Built", "Finding → Calculation"),
                    ("Compare expected vs billed", "Built", "Finding → price chart"),
                    ("Prioritised potential leakage findings", "Built", "Leakage Analysis"),
                    ("Finance validates discrepancy", "Built", "Review Queue → decision"),
                    ("Resolve, dispute or close case", "Built (decision only)", "Review Queue"),
                    ("Correct billing or initiate recovery", "Pilot", "Draft rebilling note only"),
                    ("Track invoice, receivable and cash receipt", "Pilot", "-"),
                    (
                        "Measure validated value and cash recovered",
                        "Partly built",
                        "Business Impact",
                    ),
                ],
                columns=["Step", "Status", "In the app"],
            ),
            hide_index=True,
            width="stretch",
            height=490,
        )
        st.page_link(PAGES["arch"], label="Technical architecture", icon=":material/architecture:")


# ---------------------------------------------------------------- Technical Architecture
def page_arch() -> None:
    st.title("Technical Architecture")
    st.caption(
        "For AI and technology reviewers: data ingestion, AI extraction, deterministic calculation, "
        "validation, and the application layer."
    )
    st.link_button("Open the GitHub repository", REPO_URL, icon=":material/code:")
    tabs = st.tabs(["Architecture", "AI vs rules", "Evaluation scorecard"])
    with tabs[0]:
        if ARCH_DOC.exists():
            # Mermaid does not render in st.markdown; the same content is in the tables below it.
            text = re.sub(r"```mermaid.*?```", "", ARCH_DOC.read_text(encoding="utf-8"), flags=re.S)
            st.markdown(text.split("\n", 1)[1] if text.startswith("# ") else text)
        else:
            st.info("docs/technical_architecture.md not found.")
    with tabs[1]:
        ai_vs_rules()
    with tabs[2]:
        scorecard()


def ai_vs_rules() -> None:
    st.markdown(
        "**Why AI?** The same obligation is written many ways. Rules handle the standard phrasing and miss the "
        "rest. Small reading errors become large money errors."
    )
    ext = REPORTS / "extraction_summary.json"
    if not ext.exists():
        st.info(
            "Run `python -m src.extract.run_extraction --extractor both` then `python -m src.evaluate_extraction`."
        )
        return
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
                    Decimal(ev["overbilling_detected_usd"]) - Decimal(ev["overbilling_seeded_usd"])
                )
                if ev
                else "-",
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("Development set (synthetic, not blind). Not an independent validation result.")
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


def scorecard() -> None:
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


# ---------------------------------------------------------------- navigation
PAGES = {
    "home": st.Page(page_home, title="Home", icon=":material/home:", url_path="home", default=True),
    "analysis": st.Page(
        page_analysis, title="Leakage Analysis", icon=":material/search:", url_path="analysis"
    ),
    "review": st.Page(
        page_review, title="Review Queue", icon=":material/fact_check:", url_path="review"
    ),
    "impact": st.Page(
        page_impact, title="Business Impact", icon=":material/payments:", url_path="impact"
    ),
    "flow": st.Page(
        page_flow, title="End-to-End Flow", icon=":material/account_tree:", url_path="flow"
    ),
    "arch": st.Page(
        page_arch,
        title="Technical Architecture",
        icon=":material/architecture:",
        url_path="architecture",
    ),
}
st.navigation(
    {
        "Business journey": [PAGES[k] for k in ("home", "analysis", "review", "impact")],
        "How it works": [PAGES[k] for k in ("flow", "arch")],
    }
).run()
