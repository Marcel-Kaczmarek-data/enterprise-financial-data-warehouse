"""Page 8 - Revenue & Profitability."""

import plotly.graph_objects as go
import streamlit as st
from lib.data import q
from lib.ui import SERIES, chart_layout, kpi, money, page_header, pct, sidebar_filters

f = sidebar_filters()
page_header("Revenue & Profitability", "Gross invoiced revenue by geography, product and customer segment", f)

rev = q(
    """select * from finance_marts.mart_revenue_analysis where fiscal_year in (?, ?)
           and (? = 'GROUP' or entity_id = ?)""",
    f.fiscal_year,
    f.fiscal_year - 1,
    f.entity_id,
    f.entity_id,
)
cur = rev[(rev["fiscal_year"] == f.fiscal_year) & (rev["fiscal_period"] <= f.fiscal_period)]
prev = rev[(rev["fiscal_year"] == f.fiscal_year - 1) & (rev["fiscal_period"].str[5:] <= f.fiscal_period[5:])]
total, total_py = cur["revenue_reporting"].sum(), prev["revenue_reporting"].sum()

cust = q(
    """select customer_id, sum(invoice_amount_reporting) r from finance_core.fact_customer_invoices
            where not is_intercompany and fiscal_period between ? and ? and (? = 'GROUP' or entity_id = ?)
            group by 1 order by r desc""",
    f.periods_in_year[0],
    f.fiscal_period,
    f.entity_id,
    f.entity_id,
)
top10 = cust.head(10)["r"].sum() / cust["r"].sum() if len(cust) else None
c = st.columns(4)
kpi(
    c[0],
    "Invoiced revenue YTD",
    money(total),
    f"{pct((total - total_py) / total_py, signed=True)} vs prior year" if total_py else None,
    delta_good=total >= total_py if total_py else None,
)
kpi(c[1], "Active customers YTD", f"{len(cust):,}")
kpi(c[2], "Top-10 customer concentration", pct(top10), "share of invoiced revenue")
kpi(c[3], "Average revenue per customer", money(total / len(cust)) if len(cust) else "–")

left, right = st.columns(2)
geo = cur.groupby("customer_country", as_index=False)["revenue_reporting"].sum().sort_values("revenue_reporting")
fig = go.Figure(
    go.Bar(
        x=geo["revenue_reporting"],
        y=geo["customer_country"],
        orientation="h",
        marker_color=SERIES[0],
        hovertemplate="%{y}: €%{x:,.0f}<extra></extra>",
    )
)
fig = chart_layout(fig, "Revenue by customer country (YTD)", legend=False, height=380)
fig.update_layout(hovermode="closest")
fig.update_xaxes(tickprefix="€", tickformat="~s", showgrid=True, gridcolor="#e9e9e9")
fig.update_yaxes(tickprefix=None, tickformat=None)
left.plotly_chart(fig, use_container_width=True)

lines = cur.groupby(["fiscal_period", "product_line"], as_index=False)["revenue_reporting"].sum()
fig = go.Figure()
for i, pl in enumerate(sorted(lines["product_line"].unique())):
    d = lines[lines["product_line"] == pl]
    fig.add_bar(x=d["fiscal_period"], y=d["revenue_reporting"], name=pl, marker_color=SERIES[i])
fig.update_layout(barmode="stack")
right.plotly_chart(chart_layout(fig, "Revenue by product line (monthly)", height=380), use_container_width=True)

left, right = st.columns(2)
seg = cur.groupby("customer_segment", as_index=False)["revenue_reporting"].sum()
seg_py = (
    prev.groupby("customer_segment", as_index=False)["revenue_reporting"]
    .sum()
    .rename(columns={"revenue_reporting": "py"})
)
seg = seg.merge(seg_py, on="customer_segment", how="left").sort_values("revenue_reporting", ascending=False)
fig = go.Figure()
fig.add_bar(x=seg["customer_segment"], y=seg["py"], name=f"{f.fiscal_year - 1} same period", marker_color="#9dc8f7")
fig.add_bar(x=seg["customer_segment"], y=seg["revenue_reporting"], name=str(f.fiscal_year), marker_color=SERIES[0])
left.plotly_chart(chart_layout(fig, "Revenue by customer segment vs prior year"), use_container_width=True)

margin = q(
    """select entity_id, sum(revenue) revenue, sum(gross_profit) gp, sum(ebitda) ebitda
              from finance_marts.mart_executive_financial_summary
              where reporting_scope = 'STANDALONE' and fiscal_period between ? and ? group by 1 having sum(revenue) > 0""",
    f.periods_in_year[0],
    f.fiscal_period,
)
margin = margin[~margin["entity_id"].isin(["E01", "E10", "E15"])]
margin["gm"], margin["em"] = margin["gp"] / margin["revenue"], margin["ebitda"] / margin["revenue"]
margin = margin.sort_values("em")
fig = go.Figure()
fig.add_bar(y=margin["entity_id"], x=margin["gm"], name="Gross margin", orientation="h", marker_color=SERIES[0])
fig.add_bar(y=margin["entity_id"], x=margin["em"], name="EBITDA margin", orientation="h", marker_color=SERIES[2])
fig = chart_layout(fig, "Margin analysis by operating subsidiary (YTD)", y_money=False)
fig.update_layout(hovermode="y unified")
fig.update_xaxes(tickformat=".0%", showgrid=True, gridcolor="#e9e9e9")
right.plotly_chart(fig, use_container_width=True)

dept = q(
    """select department_name, sum(expense_reporting) cost from finance_marts.mart_department_performance
            where fiscal_period between ? and ? and (? = 'GROUP' or entity_id = ?) group by 1 order by cost desc""",
    f.periods_in_year[0],
    f.fiscal_period,
    f.entity_id,
    f.entity_id,
)
fig = go.Figure(
    go.Bar(
        x=dept["department_name"],
        y=dept["cost"],
        marker_color=SERIES[1],
        hovertemplate="%{x}: €%{y:,.0f}<extra></extra>",
    )
)
st.plotly_chart(
    chart_layout(fig, "Cost base by department (YTD) - profitability drivers", legend=False), use_container_width=True
)
st.caption("Revenue here is gross invoiced revenue before credit notes; net revenue is on the Profit and Loss page.")
