"""Page 1 - CFO Executive Overview."""

import plotly.graph_objects as go
import streamlit as st
from lib.data import q
from lib.ui import (
    SERIES,
    chart_layout,
    kpi,
    money,
    page_header,
    pct,
    sidebar_filters,
    status_badge,
)

f = sidebar_filters()
page_header("CFO Executive Overview", "Year-to-date performance, liquidity and control status", f)

summary = q(
    """select * from finance_marts.mart_executive_financial_summary
               where reporting_scope = ? and entity_id = ? order by fiscal_period""",
    f.scope,
    f.entity_id,
)
ytd = summary[summary["fiscal_period"].isin(f.periods_in_year)]
py_periods = [f"{f.fiscal_year - 1}{p[4:]}" for p in f.periods_in_year]
py = summary[summary["fiscal_period"].isin(py_periods)]
cur = summary[summary["fiscal_period"] == f.fiscal_period].iloc[0]


def ytd_sum(df, col):
    return df[col].sum() if len(df) else None


rev, rev_py = ytd_sum(ytd, "revenue"), ytd_sum(py, "revenue")
ebitda, np_ = ytd_sum(ytd, "ebitda"), ytd_sum(ytd, "net_profit")
opex = ytd_sum(ytd, "operating_expenses")
budget_rev = ytd_sum(ytd, "budget_revenue")
rev_var = ytd_sum(ytd, "revenue_budget_variance")

c = st.columns(4)
kpi(
    c[0],
    "Revenue YTD",
    money(rev),
    f"{pct((rev - rev_py) / rev_py, signed=True)} vs prior year" if rev_py else None,
    delta_good=(rev >= rev_py) if rev_py else None,
)
kpi(c[1], "EBITDA YTD", money(ebitda), f"{pct(ebitda / rev)} margin" if rev else None)
kpi(c[2], "Net profit YTD", money(np_), f"{pct(np_ / rev)} margin" if rev else None)
kpi(
    c[3],
    "Operating expenses YTD",
    money(opex),
    f"{pct((opex - ytd_sum(py, 'operating_expenses')) / ytd_sum(py, 'operating_expenses'), signed=True)} vs prior year"
    if len(py)
    else None,
)
st.write("")
c = st.columns(4)
kpi(c[0], "Cash position", money(cur["cash"]), f"at {f.fiscal_period} month end")
kpi(
    c[1],
    "Working capital",
    money(cur["working_capital"]),
    f"current ratio {cur['current_ratio']:.2f}" if cur["current_ratio"] == cur["current_ratio"] else None,
)
kpi(
    c[2],
    "Revenue vs budget YTD",
    money(rev_var, signed=True),
    f"budget {money(budget_rev)} (original, base)" if budget_rev else "no budget",
    delta_good=(rev_var or 0) >= 0,
)
kpi(
    c[3],
    "Days sales outstanding",
    f"{cur['days_sales_outstanding']:.0f} days"
    if cur["days_sales_outstanding"] == cur["days_sales_outstanding"]
    else "–",
    "trailing 3-month revenue basis",
)

st.write("")
left, right = st.columns([3, 2])
trend = summary[summary["fiscal_period"] >= f"{f.fiscal_year - 1}-01"]
trend = trend[trend["fiscal_period"] <= f.fiscal_period]
fig = go.Figure()
fig.add_bar(x=trend["fiscal_period"], y=trend["revenue"], name="Revenue", marker_color=SERIES[0])
fig.add_bar(x=trend["fiscal_period"], y=trend["operating_expenses"], name="Operating expenses", marker_color=SERIES[1])
fig.add_scatter(
    x=trend["fiscal_period"],
    y=trend["net_profit"],
    name="Net profit",
    mode="lines+markers",
    line={"color": SERIES[2], "width": 2},
    marker={"size": 8},
)
left.plotly_chart(chart_layout(fig, "Monthly revenue, operating expenses and net profit"), use_container_width=True)

ents = q(
    """select s.entity_id, e.entity_name, e.country_name, sum(s.revenue) revenue, sum(s.ebitda) ebitda
            from finance_marts.mart_executive_financial_summary s join finance_core.dim_legal_entity e using (entity_id)
            where s.reporting_scope = 'STANDALONE' and s.fiscal_period between ? and ?
            group by 1, 2, 3 having sum(s.revenue) > 0 order by revenue""",
    f.periods_in_year[0],
    f.fiscal_period,
)
ext = ents[~ents["entity_id"].isin(["E01", "E10", "E15"])]
fig = go.Figure(
    go.Bar(
        x=ext["revenue"],
        y=ext["entity_name"].str.replace(
            r" (GmbH|Ltd|SAS|AG|AB|Inc\.|K\.K\.|Pte\. Ltd\.|Pvt\. Ltd\.)$", "", regex=True
        ),
        orientation="h",
        marker_color=SERIES[0],
        name="Revenue YTD",
        hovertemplate="%{y}<br>Revenue YTD €%{x:,.0f}<extra></extra>",
    )
)
fig = chart_layout(fig, "Revenue by subsidiary (YTD, standalone)", legend=False)
fig.update_layout(hovermode="closest")
fig.update_xaxes(tickprefix="€", tickformat="~s", showgrid=True, gridcolor="#e9e9e9")
fig.update_yaxes(tickprefix=None, tickformat=None, showgrid=False)
right.plotly_chart(fig, use_container_width=True)

left, right = st.columns([3, 2])
cf = q(
    """select cash_flow_section, sum(amount_reporting) amount from finance_marts.mart_cash_flow
          where reporting_scope = ? and entity_id = ? and fiscal_period between ? and ?
          group by 1 order by min(section_order)""",
    f.scope,
    f.entity_id,
    f.periods_in_year[0],
    f.fiscal_period,
)
names = {"OPERATING": "Operating", "INVESTING": "Investing", "FINANCING": "Financing", "FX_EFFECT": "FX effect"}
opening = q(
    """select any_value(opening_cash_reporting) o from finance_marts.mart_cash_flow
               where reporting_scope = ? and entity_id = ? and fiscal_period = ?""",
    f.scope,
    f.entity_id,
    f.periods_in_year[0],
)["o"].iloc[0]
fig = go.Figure(
    go.Waterfall(
        x=["Opening cash"] + [names[s] for s in cf["cash_flow_section"]] + ["Closing cash"],
        measure=["absolute"] + ["relative"] * len(cf) + ["total"],
        y=[opening, *cf["amount"].tolist(), 0],
        increasing={"marker": {"color": SERIES[0]}},
        decreasing={"marker": {"color": SERIES[1]}},
        totals={"marker": {"color": "#666666"}},
        connector={"line": {"color": "#cfcfcf"}},
        hovertemplate="%{x}: €%{y:,.0f}<extra></extra>",
    )
)
left.plotly_chart(chart_layout(fig, "Cash flow summary YTD (direct method)", legend=False), use_container_width=True)

with right:
    st.markdown("##### Key financial alerts")
    exc = q(
        """select severity, exception_domain, count(*) n from finance_marts.mart_financial_exceptions
               where fiscal_period = ? group by 1, 2 order by 1, 3 desc""",
        f.fiscal_period,
    )
    close = q(
        """select avg(close_completion_rate) rate, sum(case when period_status = 'CLOSED' then 1 else 0 end) closed,
                 count(*) n from finance_marts.mart_financial_close where fiscal_period = ?""",
        f.fiscal_period,
    )
    crit = int(exc.loc[exc["severity"] == "CRITICAL", "n"].sum())
    warn = int(exc.loc[exc["severity"] == "WARNING", "n"].sum())
    st.markdown(
        status_badge("critical" if crit else "good", f"{crit} critical exceptions in {f.fiscal_period}"),
        unsafe_allow_html=True,
    )
    st.markdown(status_badge("warning" if warn else "good", f"{warn} items awaiting review"), unsafe_allow_html=True)
    r = close.iloc[0]
    st.markdown(
        status_badge(
            "good" if r["closed"] == r["n"] else "warning",
            f"Close: {int(r['closed'])}/{int(r['n'])} entities closed · {pct(r['rate'], 0)} tasks complete",
        ),
        unsafe_allow_html=True,
    )
    gm = cur["gross_margin"]
    st.markdown(
        status_badge("good" if gm and gm > 0.6 else "serious", f"Gross margin {pct(gm)} in {f.fiscal_period}"),
        unsafe_allow_html=True,
    )
    if len(exc):
        st.dataframe(
            exc.rename(columns={"severity": "Severity", "exception_domain": "Domain", "n": "Items"}),
            hide_index=True,
            use_container_width=True,
            height=210,
        )
    st.caption("Financial statements are actuals. Expected cash flows and forecasts are estimates and labelled so.")
