"""Page 11 - Financial Reconciliation (review queue)."""

import plotly.graph_objects as go
import streamlit as st
from lib.data import q
from lib.ui import SERIES, STATUS, chart_layout, kpi, page_header, pct, sidebar_filters, table_with_export

f = sidebar_filters()
page_header(
    "Financial Reconciliation",
    "Bank, subledger, intercompany and three-way match results - ambiguous items are never auto-approved",
    f,
)

bank = q(
    """select item_side, match_status, match_rule, count(*) n, sum(abs(amount)) amt
            from finance_intermediate.int_bank_transaction_matching
            where fiscal_period <= ? and (? = 'GROUP' or entity_id = ?) group by 1, 2, 3""",
    f.fiscal_period,
    f.entity_id,
    f.entity_id,
)
bank_lines = bank[bank["item_side"] == "BANK"]
matched = bank_lines.loc[bank_lines["match_status"] == "MATCHED", "n"].sum()
total = bank_lines["n"].sum()
exc = q(
    """select * from finance_marts.mart_financial_exceptions where fiscal_period <= ?
           and (? = 'GROUP' or entity_id = ? or entity_id is null)""",
    f.fiscal_period,
    f.entity_id,
    f.entity_id,
)
c = st.columns(4)
kpi(c[0], "Bank reconciliation rate", pct(matched / total) if total else "–", f"{matched:,} of {total:,} bank lines")
kpi(
    c[1],
    "Unmatched bank / ledger",
    f"{int(bank.loc[bank['match_status'].isin(['UNMATCHED_BANK', 'UNMATCHED_LEDGER']), 'n'].sum()):,}",
    f"{int(bank.loc[bank['match_status'] == 'POSSIBLE_DUPLICATE', 'n'].sum())} possible duplicate debits",
)
kpi(
    c[2],
    "Intercompany exceptions",
    f"{int((exc['exception_domain'] == 'INTERCOMPANY').sum()):,}",
    "beyond 2% tolerance",
)
kpi(
    c[3],
    "Three-way match exceptions",
    f"{int((exc['exception_domain'] == 'PROCURE_TO_PAY').sum()):,}",
    f"{int(((exc['exception_domain'] == 'PROCURE_TO_PAY') & (exc['severity'] == 'CRITICAL')).sum())} duplicates paid",
)

left, right = st.columns(2)
rules = bank_lines.groupby(["match_status", "match_rule"], dropna=False, as_index=False)["n"].sum()
rules["label"] = rules.apply(lambda r: r.match_rule if r.match_status == "MATCHED" else r.match_status, axis=1)
rules = rules.sort_values("n")
colors = {"BANK_ORIGINATED": SERIES[0], "EXACT_REFERENCE": SERIES[0], "AMOUNT_DATE": SERIES[2]}
fig = go.Figure(
    go.Bar(
        x=rules["n"],
        y=rules["label"],
        orientation="h",
        marker_color=[
            colors.get(lbl, STATUS["critical"] if "UNMATCHED" in lbl or "DUPLICATE" in lbl else STATUS["warning"])
            for lbl in rules["label"]
        ],
        hovertemplate="%{y}: %{x:,} bank lines<extra></extra>",
    )
)
fig = chart_layout(fig, "Bank statement lines by match rule / status", legend=False, y_money=False)
fig.update_layout(hovermode="closest")
fig.update_xaxes(type="log", title="lines (log scale)", showgrid=True, gridcolor="#e9e9e9")
left.plotly_chart(fig, use_container_width=True)

dom = exc.groupby(["exception_domain", "severity"], as_index=False).size()
fig = go.Figure()
for sev in ["CRITICAL", "WARNING", "INFO"]:
    d = dom[dom["severity"] == sev]
    fig.add_bar(
        x=d["exception_domain"],
        y=d["size"],
        name=sev.title(),
        marker_color={"CRITICAL": STATUS["critical"], "WARNING": STATUS["warning"], "INFO": "#b4b4b4"}[sev],
    )
fig.update_layout(barmode="stack")
right.plotly_chart(chart_layout(fig, "Open exceptions by domain and severity", y_money=False), use_container_width=True)

st.markdown("##### Exception investigation queue")
c1, c2 = st.columns(2)
domains = c1.multiselect(
    "Domain", sorted(exc["exception_domain"].unique()), default=sorted(exc["exception_domain"].unique())
)
sev = c2.multiselect("Severity", ["CRITICAL", "WARNING", "INFO"], default=["CRITICAL", "WARNING"])
view = exc[exc["exception_domain"].isin(domains) & exc["severity"].isin(sev)].sort_values(
    ["severity", "fiscal_period"], ascending=[True, False]
)
table_with_export(
    view[
        [
            "severity",
            "exception_domain",
            "exception_type",
            "entity_id",
            "fiscal_period",
            "discrepancy_amount",
            "currency",
            "affected_object",
            "affected_ids",
            "explanation",
        ]
    ],
    "exception_queue",
    height=420,
)
