"""Page 3 - Balance Sheet (point-in-time) with the accounting equation check."""

import plotly.graph_objects as go
import streamlit as st
from lib.data import q
from lib.ui import SERIES, chart_layout, kpi, money, page_header, sidebar_filters, status_badge

f = sidebar_filters()
page_header("Balance Sheet", "Point-in-time closing balances at month end (never summed across dates)", f)

bs = q(
    """select * from finance_marts.mart_balance_sheet where reporting_scope = ? and entity_id = ?
          order by fiscal_period, line_order""",
    f.scope,
    f.entity_id,
)
cur = bs[bs["fiscal_period"] == f.fiscal_period]
prev_year_end = f"{f.fiscal_year - 1}-12"
prev = bs[bs["fiscal_period"] == prev_year_end].set_index("statement_line")["amount_reporting"]

assets = cur.loc[cur["section"] == "Assets", "amount_reporting"].sum()
liab = cur.loc[cur["section"] == "Liabilities", "amount_reporting"].sum()
equity = cur.loc[cur["section"] == "Equity", "amount_reporting"].sum()
diff = cur["accounting_equation_difference"].iloc[0]

c = st.columns(4)
kpi(c[0], "Total assets", money(assets))
kpi(c[1], "Total liabilities", money(liab))
kpi(c[2], "Total equity", money(equity))
with c[3]:
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
    ok = abs(diff) < 0.01
    st.markdown(
        status_badge(
            "good" if ok else "critical", "Assets = Liabilities + Equity" if ok else f"Out of balance by {money(diff)}"
        ),
        unsafe_allow_html=True,
    )
    st.caption(f"Difference: €{diff:,.2f} (tested on every entity and period)")

left, right = st.columns([5, 4])
with left:
    table = cur[["section", "subsection", "statement_line", "amount_reporting"]].copy()
    table[f"{prev_year_end}"] = table["statement_line"].map(prev)
    table["Change"] = table["amount_reporting"] - table[f"{prev_year_end}"]
    table = table.rename(
        columns={
            "section": "Section",
            "subsection": "Group",
            "statement_line": "Line",
            "amount_reporting": f.fiscal_period,
        }
    )
    st.markdown("##### Statement of financial position (EUR)")
    st.dataframe(
        table.style.format(dict.fromkeys([f.fiscal_period, prev_year_end, "Change"], "€{:,.0f}"), na_rep="–"),
        hide_index=True,
        use_container_width=True,
        height=700,
    )

with right:
    comp = cur[(cur["section"] == "Assets") & (cur["amount_reporting"] > 0)]
    fig = go.Figure(
        go.Bar(
            x=comp["amount_reporting"],
            y=comp["statement_line"],
            orientation="h",
            marker_color=SERIES[0],
            hovertemplate="%{y}: €%{x:,.0f}<extra></extra>",
        )
    )
    fig = chart_layout(fig, "Asset composition", legend=False, height=300)
    fig.update_layout(hovermode="closest")
    fig.update_xaxes(tickprefix="€", tickformat="~s", showgrid=True, gridcolor="#e9e9e9")
    fig.update_yaxes(tickprefix=None, tickformat=None)
    st.plotly_chart(fig, use_container_width=True)

    hist = bs[bs["fiscal_period"].str.endswith("-12") | (bs["fiscal_period"] == f.fiscal_period)]
    hist = hist[hist["fiscal_period"] <= f.fiscal_period]
    agg = hist.groupby(["fiscal_period", "section"], as_index=False)["amount_reporting"].sum()
    fig = go.Figure()
    for i, sec in enumerate(["Assets", "Liabilities", "Equity"]):
        d = agg[agg["section"] == sec]
        fig.add_bar(x=d["fiscal_period"], y=d["amount_reporting"], name=sec, marker_color=SERIES[i])
    fig = chart_layout(fig, "Year-end history (and current period)", height=300)
    fig.update_xaxes(type="category")  # periods are labels, not dates (a date axis shifts Dec bars to next year)
    st.plotly_chart(fig, use_container_width=True)

    debt = cur[
        cur["statement_line"].isin(
            ["Short-term debt", "Long-term debt", "Accounts payable", "Accrued expenses", "Tax liabilities"]
        )
    ]
    fig = go.Figure(
        go.Bar(
            x=debt["statement_line"],
            y=debt["amount_reporting"],
            marker_color=SERIES[1],
            hovertemplate="%{x}: €%{y:,.0f}<extra></extra>",
        )
    )
    st.plotly_chart(
        chart_layout(fig, "Liability and debt structure", legend=False, height=260), use_container_width=True
    )

st.caption(
    "Translation: monetary items at closing rate; equity at historical rates; results at average rates. "
    "The currency translation adjustment (CTA) is the balancing figure of translation, never a plug for errors."
)
