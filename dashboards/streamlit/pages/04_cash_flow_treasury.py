"""Page 4 - Cash Flow & Treasury."""

import plotly.graph_objects as go
import streamlit as st
from lib.data import q
from lib.ui import SERIES, chart_layout, kpi, money, money_columns, page_header, sidebar_filters, table_with_export

f = sidebar_filters()
page_header("Cash Flow & Treasury", "Direct-method cash flow, bank positions and expected flows", f)

cf = q(
    """select * from finance_marts.mart_cash_flow where reporting_scope = ? and entity_id = ?
          order by fiscal_period, section_order""",
    f.scope,
    f.entity_id,
)
ytd = cf[cf["fiscal_period"].isin(f.periods_in_year)]
opening = ytd[ytd["fiscal_period"] == f.periods_in_year[0]]["opening_cash_reporting"].iloc[0]
closing = ytd[ytd["fiscal_period"] == f.fiscal_period]["closing_cash_reporting"].iloc[0]
by_sec = ytd.groupby("cash_flow_section")["amount_reporting"].sum()

c = st.columns(5)
kpi(c[0], "Opening cash (year)", money(opening))
kpi(c[1], "Operating cash flow YTD", money(by_sec.get("OPERATING", 0), signed=True))
kpi(c[2], "Investing cash flow YTD", money(by_sec.get("INVESTING", 0), signed=True))
kpi(c[3], "Financing cash flow YTD", money(by_sec.get("FINANCING", 0), signed=True))
kpi(c[4], "Closing cash", money(closing), f"FX effect {money(by_sec.get('FX_EFFECT', 0), signed=True)}")

left, right = st.columns([4, 5])
with left:
    st.markdown("##### Cash flow statement YTD (EUR)")
    stmt = ytd.groupby(["section_order", "cash_flow_section", "cash_flow_line"], as_index=False)[
        "amount_reporting"
    ].sum()
    stmt = stmt.sort_values(["section_order", "amount_reporting"])
    st.dataframe(
        stmt[["cash_flow_section", "cash_flow_line", "amount_reporting"]]
        .rename(columns={"cash_flow_section": "Section", "cash_flow_line": "Line", "amount_reporting": "YTD"})
        .style.format({"YTD": "€{:,.0f}"}),
        hide_index=True,
        use_container_width=True,
        height=470,
    )
    check = opening + ytd["amount_reporting"].sum() - closing
    st.caption(
        f"Reconciliation: opening + flows + FX effect − closing = €{check:,.2f}. "
        "Internal transfers are excluded; intercompany settlements are removed on consolidation."
    )

with right:
    trend = cf[(cf["fiscal_period"] <= f.fiscal_period) & (cf["fiscal_period"] >= f"{f.fiscal_year - 1}-01")]
    piv = (
        trend.pivot_table(index="fiscal_period", columns="cash_flow_section", values="amount_reporting", aggfunc="sum")
        .fillna(0)
        .reset_index()
    )
    fig = go.Figure()
    for i, sec in enumerate(["OPERATING", "INVESTING", "FINANCING"]):
        if sec in piv:
            fig.add_bar(x=piv["fiscal_period"], y=piv[sec], name=sec.title(), marker_color=SERIES[i])
    fig.update_layout(barmode="relative")
    st.plotly_chart(chart_layout(fig, "Monthly cash flow by activity"), use_container_width=True)

pos = q(
    """select * from finance_marts.mart_cash_position where balance_date = (
              select max(balance_date) from finance_marts.mart_cash_position where fiscal_period = ?)
           and (? = 'GROUP' or entity_id = ?)""",
    f.fiscal_period,
    f.entity_id,
    f.entity_id,
)
left, right = st.columns(2)
by_ccy = pos.groupby("currency", as_index=False)["book_balance_reporting"].sum().sort_values("book_balance_reporting")
fig = go.Figure(
    go.Bar(
        x=by_ccy["book_balance_reporting"],
        y=by_ccy["currency"],
        orientation="h",
        marker_color=SERIES[0],
        hovertemplate="%{y}: €%{x:,.0f}<extra></extra>",
    )
)
fig = chart_layout(fig, "Cash by account currency (EUR equivalent)", legend=False, height=320)
fig.update_layout(hovermode="closest")
fig.update_xaxes(tickprefix="€", tickformat="~s", showgrid=True, gridcolor="#e9e9e9")
fig.update_yaxes(tickprefix=None, tickformat=None)
left.plotly_chart(fig, use_container_width=True)

inflow = pos["expected_inflows_30d_reporting"].sum()
outflow = pos["expected_outflows_30d_reporting"].sum()
fig = go.Figure(
    go.Bar(
        x=["Expected inflows (AR due ≤30d)", "Expected outflows (AP due ≤30d)"],
        y=[inflow, -outflow],
        marker_color=[SERIES[0], SERIES[1]],
        hovertemplate="%{x}: €%{y:,.0f}<extra></extra>",
    )
)
right.plotly_chart(
    chart_layout(fig, "Expected cash flows next 30 days (operational estimate)", legend=False, height=320),
    use_container_width=True,
)

fc = q("""select target_period, forecast_value from finance_marts.mart_financial_forecast
          where metric = 'OPERATING_CASH_FLOW' and forecast_type = 'FORWARD' order by 1""")
hist = q("""select fiscal_period, operating_cash_flow from finance_marts.mart_executive_financial_summary
            where reporting_scope = 'CONSOLIDATED' order by 1""").tail(18)
fig = go.Figure()
fig.add_scatter(
    x=hist["fiscal_period"],
    y=hist["operating_cash_flow"],
    name="Actual (consolidated)",
    line={"color": SERIES[0], "width": 2},
    mode="lines+markers",
    marker={"size": 8},
)
fig.add_scatter(
    x=fc["target_period"],
    y=fc["forecast_value"],
    name="Forecast (baseline)",
    line={"color": SERIES[1], "width": 2, "dash": "dash"},
    mode="lines+markers",
    marker={"size": 8},
)
st.plotly_chart(
    chart_layout(fig, "Operating cash flow: actual and 6-month baseline forecast (forecast = estimate)"),
    use_container_width=True,
)

st.markdown("##### Cash position by bank account")
table_with_export(
    pos[
        [
            "entity_id",
            "bank_account_id",
            "bank_name",
            "account_purpose",
            "currency",
            "book_balance",
            "bank_balance",
            "bank_minus_book",
            "book_balance_reporting",
        ]
    ],
    "cash_position",
    height=320,
    column_config=money_columns(["book_balance_reporting"]),
)
