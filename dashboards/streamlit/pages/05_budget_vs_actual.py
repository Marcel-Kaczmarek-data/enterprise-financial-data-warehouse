"""Page 5 - Budget versus Actual."""

import plotly.graph_objects as go
import streamlit as st
from lib.data import q
from lib.ui import (
    FAVOURABLE,
    SERIES,
    UNFAVOURABLE,
    chart_layout,
    kpi,
    money,
    money_columns,
    page_header,
    pct,
    sidebar_filters,
    table_with_export,
)

f = sidebar_filters()
page_header(
    "Budget vs Actual", "Variance analysis by version and scenario (favourable rules differ for revenue and cost)", f
)

versions = q("select distinct budget_version, scenario from finance_marts.mart_budget_vs_actual order by 1, 2")
c1, c2 = st.columns(2)
version = c1.selectbox("Budget version", sorted(versions["budget_version"].unique()), index=0)
scenario = c2.selectbox(
    "Scenario", sorted(versions.loc[versions["budget_version"] == version, "scenario"].unique()), index=0
)

base = q(
    """select * from finance_marts.mart_budget_vs_actual
            where budget_version = ? and scenario = ? and fiscal_year = ? and fiscal_period <= ?
              and (? = 'GROUP' or entity_id = ?)""",
    version,
    scenario,
    f.fiscal_year,
    f.fiscal_period,
    f.entity_id,
    f.entity_id,
)
if base.empty:
    st.info("No budget lines for this selection (for example, revised budgets exist only from July).")
    st.stop()

rev = base[base["is_revenue"]]
cost = base[~base["is_revenue"]]
r_act, r_bud = rev["actual_amount_reporting"].sum(), rev["budget_amount_reporting"].sum()
c_act, c_bud = cost["actual_amount_reporting"].sum(), cost["budget_amount_reporting"].sum()
c = st.columns(4)
kpi(
    c[0],
    "Revenue actual YTD",
    money(r_act),
    f"{money(r_act - r_bud, signed=True)} vs budget",
    delta_good=r_act >= r_bud,
)
kpi(c[1], "Revenue budget YTD", money(r_bud), f"{pct(r_act / r_bud)} achieved" if r_bud else None)
kpi(
    c[2],
    "Expenses actual YTD",
    money(c_act),
    f"{money(c_act - c_bud, signed=True)} vs budget",
    delta_good=c_act <= c_bud,
)
kpi(c[3], "Budget utilization (costs)", pct(c_act / c_bud) if c_bud else "–", f"remaining {money(c_bud - c_act)}")

left, right = st.columns(2)
monthly = base.groupby(["fiscal_period", "is_revenue"], as_index=False)[
    ["actual_amount_reporting", "budget_amount_reporting"]
].sum()
for col, is_rev, title in [(left, True, "Revenue: actual vs budget"), (right, False, "Expenses: actual vs budget")]:
    d = monthly[monthly["is_revenue"] == is_rev]
    fig = go.Figure()
    fig.add_bar(x=d["fiscal_period"], y=d["actual_amount_reporting"], name="Actual", marker_color=SERIES[0])
    fig.add_scatter(
        x=d["fiscal_period"],
        y=d["budget_amount_reporting"],
        name=f"Budget ({version}/{scenario})",
        mode="lines+markers",
        line={"color": SERIES[1], "width": 2},
        marker={"size": 8},
    )
    col.plotly_chart(chart_layout(fig, title, height=320), use_container_width=True)

# Variance waterfall: budget operating result -> line variances (signed by favourability) -> actual
lines = base.groupby(["statement_line", "is_revenue"], as_index=False)[
    ["actual_amount_reporting", "budget_amount_reporting"]
].sum()
lines["impact"] = lines.apply(
    lambda r: (r.actual_amount_reporting - r.budget_amount_reporting) * (1 if r.is_revenue else -1), axis=1
)
lines = lines.sort_values("impact")
budget_result = r_bud - c_bud
fig = go.Figure(
    go.Waterfall(
        x=["Budgeted result", *lines["statement_line"].tolist(), "Actual result"],
        measure=["absolute"] + ["relative"] * len(lines) + ["total"],
        y=[budget_result, *lines["impact"].tolist(), 0],
        increasing={"marker": {"color": FAVOURABLE}},
        decreasing={"marker": {"color": UNFAVOURABLE}},
        totals={"marker": {"color": "#666666"}},
        connector={"line": {"color": "#cfcfcf"}},
        hovertemplate="%{x}: €%{y:,.0f}<extra></extra>",
    )
)
fig = chart_layout(
    fig, "Budget variance waterfall YTD (blue = favourable, orange = unfavourable)", legend=False, height=380
)
st.plotly_chart(fig, use_container_width=True)

st.markdown("##### Departmental budget utilization (expenses, YTD)")
dept = cost.groupby(["department_name", "functional_area"], as_index=False)[
    ["actual_amount_reporting", "budget_amount_reporting"]
].sum()
dept["variance"] = dept["actual_amount_reporting"] - dept["budget_amount_reporting"]
dept["utilization"] = dept["actual_amount_reporting"] / dept["budget_amount_reporting"].where(
    dept["budget_amount_reporting"] != 0
)
dept["status"] = dept["variance"].apply(lambda v: "⛔ Over budget" if v > 0 else "✅ Within budget")
table_with_export(
    dept.sort_values("variance", ascending=False),
    "department_budget_utilization",
    height=330,
    column_config=money_columns(["actual_amount_reporting", "budget_amount_reporting", "variance"])
    | {"utilization": st.column_config.ProgressColumn("utilization", format="%.0f%%", min_value=0, max_value=1.5)},
)
