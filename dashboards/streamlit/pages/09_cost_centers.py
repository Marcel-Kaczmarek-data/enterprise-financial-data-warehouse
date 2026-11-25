"""Page 9 - Cost Center and Department Analytics."""

import plotly.graph_objects as go
import streamlit as st
from lib.data import q
from lib.ui import SERIES, chart_layout, kpi, money, money_columns, page_header, sidebar_filters, table_with_export

f = sidebar_filters()
page_header("Cost Centers & Departments", "Expenditure, payroll cost and budget utilization by organisation unit", f)

areas = q("select distinct functional_area from finance_core.dim_department order by 1")["functional_area"].tolist()
sel = st.multiselect("Functional area", areas, default=areas)
perf = q(
    """select * from finance_marts.mart_department_performance
            where fiscal_period between ? and ? and (? = 'GROUP' or entity_id = ?)""",
    f"{f.fiscal_year - 1}-01",
    f.fiscal_period,
    f.entity_id,
    f.entity_id,
)
perf = perf[perf["functional_area"].isin(sel)]
ytd = perf[perf["fiscal_period"].isin(f.periods_in_year)]
payroll = ytd.loc[ytd["statement_line"] == "Salaries and benefits", "expense_reporting"].sum()
heads = ytd.loc[ytd["fiscal_period"] == f.fiscal_period, "headcount"].sum()
c = st.columns(4)
kpi(c[0], "Departmental expenditure YTD", money(ytd["expense_reporting"].sum()))
kpi(c[1], "Payroll cost YTD", money(payroll), "salaries + employer contributions")
kpi(c[2], "Headcount (period)", f"{int(heads):,}")
kpi(c[3], "Cost centers", f"{ytd['cost_center_id'].nunique():,}")

left, right = st.columns(2)
dept = ytd.groupby(["department_name", "statement_line"], as_index=False)["expense_reporting"].sum()
order = dept.groupby("department_name")["expense_reporting"].sum().sort_values().index.tolist()
fig = go.Figure()
for i, line in enumerate(sorted(dept["statement_line"].unique())[:8]):
    d = dept[dept["statement_line"] == line].set_index("department_name").reindex(order).reset_index()
    fig.add_bar(y=d["department_name"], x=d["expense_reporting"], name=line, orientation="h", marker_color=SERIES[i])
fig.update_layout(barmode="stack")
fig = chart_layout(fig, "Departmental expenditure by cost type (YTD)", height=560)
fig.update_layout(hovermode="y unified")
fig.update_xaxes(tickprefix="€", tickformat="~s", showgrid=True, gridcolor="#e9e9e9")
fig.update_yaxes(tickprefix=None, tickformat=None)
left.plotly_chart(fig, use_container_width=True)

trend = perf.groupby(["fiscal_period", "functional_area"], as_index=False)["expense_reporting"].sum()
fig = go.Figure()
for i, a in enumerate(sel):
    d = trend[trend["functional_area"] == a]
    fig.add_scatter(
        x=d["fiscal_period"], y=d["expense_reporting"], name=a, mode="lines", line={"color": SERIES[i], "width": 2}
    )
right.plotly_chart(chart_layout(fig, "Historical cost trend by functional area", height=560), use_container_width=True)

bud = q(
    """select cost_center_id, department_name, sum(actual_amount_reporting) actual, sum(budget_amount_reporting) budget
           from finance_marts.mart_budget_vs_actual
           where budget_version = 'ORIGINAL' and scenario = 'BASE' and not is_revenue
             and fiscal_period between ? and ? and (? = 'GROUP' or entity_id = ?) group by 1, 2""",
    f.periods_in_year[0],
    f.fiscal_period,
    f.entity_id,
    f.entity_id,
)
cc = (
    ytd.groupby(["cost_center_id", "cost_center_name", "department_name", "functional_area"], as_index=False)[
        "expense_reporting"
    ]
    .sum()
    .merge(bud[["cost_center_id", "budget"]], on="cost_center_id", how="left")
)
cc["utilization"] = cc["expense_reporting"] / cc["budget"].where(cc["budget"] != 0)
st.markdown("##### Cost center performance (YTD)")
table_with_export(
    cc.sort_values("expense_reporting", ascending=False),
    "cost_center_performance",
    column_config=money_columns(["expense_reporting", "budget"])
    | {"utilization": st.column_config.ProgressColumn("utilization", format="%.0f%%", min_value=0, max_value=1.5)},
)
