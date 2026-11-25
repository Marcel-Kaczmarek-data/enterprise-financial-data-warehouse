"""Page 2 - Profit and Loss with drill-through to general-ledger lines and source documents."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from lib.data import q
from lib.ui import SERIES, chart_layout, money, money_columns, page_header, pct, sidebar_filters, table_with_export

f = sidebar_filters()
page_header("Profit and Loss", "Statement by line with month, year-to-date and prior-year comparison", f)

pl = q(
    """select * from finance_marts.mart_profit_and_loss where reporting_scope = ? and entity_id = ?
          order by fiscal_period, line_order""",
    f.scope,
    f.entity_id,
)
month = pl[pl["fiscal_period"] == f.fiscal_period].sort_values("line_order")
py_period = f"{f.fiscal_year - 1}{f.fiscal_period[4:]}"
py_ytd = pl[(pl["fiscal_period"] == py_period)][["statement_line", "ytd_amount_reporting"]].rename(
    columns={"ytd_amount_reporting": "py_ytd"}
)

if f.compare == "Budget":
    bud = q(
        """select statement_line, sum(budget_amount_reporting) budget_month,
                      sum(ytd_budget_reporting) budget_ytd
               from finance_marts.mart_budget_vs_actual
               where budget_version = 'ORIGINAL' and scenario = 'BASE' and fiscal_period = ?
                 and (? = 'GROUP' or entity_id = ?) group by 1""",
        f.fiscal_period,
        f.entity_id,
        f.entity_id,
    )
    sign = {"Product revenue": 1, "Service revenue": 1, "Other operating revenue": 1, "Finance income": 1}
    bud["budget_ytd"] = bud.apply(lambda r: r["budget_ytd"] * sign.get(r["statement_line"], -1), axis=1)
    comp = bud[["statement_line", "budget_ytd"]].rename(columns={"budget_ytd": "comparison_ytd"})
    comp_label = "Budget YTD (original)"
else:
    comp = py_ytd.rename(columns={"py_ytd": "comparison_ytd"})
    comp_label = "Prior year YTD"

stmt = month[
    [
        "statement_line",
        "line_order",
        "is_subtotal",
        "amount_reporting",
        "ytd_amount_reporting",
        "prior_year_amount_reporting",
    ]
].merge(comp, on="statement_line", how="left")
stmt["variance_ytd"] = stmt["ytd_amount_reporting"] - stmt["comparison_ytd"]
show = stmt.rename(
    columns={
        "statement_line": "Line",
        "amount_reporting": f"Month {f.fiscal_period}",
        "prior_year_amount_reporting": f"Month {py_period}",
        "ytd_amount_reporting": "YTD",
        "comparison_ytd": comp_label,
        "variance_ytd": "Variance YTD",
    }
)

left, right = st.columns([5, 4])
with left:
    st.markdown("##### Statement (EUR · income positive, costs negative)")
    styled = (
        show.drop(columns=["line_order"])
        .style.apply(lambda r: ["font-weight:700;background:#f4f6f9" if r["is_subtotal"] else "" for _ in r], axis=1)
        .format({c: "€{:,.0f}" for c in show.columns if c not in ("Line", "line_order", "is_subtotal")}, na_rep="–")
    )
    st.dataframe(styled, hide_index=True, use_container_width=True, height=820, column_config={"is_subtotal": None})

with right:
    trend = pl[
        (pl["statement_line"].isin(["Total revenue", "Gross profit", "EBITDA"]))
        & (pl["fiscal_period"] <= f.fiscal_period)
        & (pl["fiscal_period"] >= f"{f.fiscal_year - 1}-01")
    ]
    piv = trend.pivot(index="fiscal_period", columns="statement_line", values="amount_reporting").reset_index()
    fig = go.Figure()
    for i, (col, name) in enumerate([("Gross profit", "Gross margin"), ("EBITDA", "EBITDA margin")]):
        fig.add_scatter(
            x=piv["fiscal_period"],
            y=piv[col] / piv["Total revenue"],
            name=name,
            mode="lines+markers",
            line={"color": SERIES[i], "width": 2},
            marker={"size": 8},
            hovertemplate="%{y:.1%}<extra>" + name + "</extra>",
        )
    fig = chart_layout(fig, "Gross margin and EBITDA margin", y_money=False, height=300)
    fig.update_yaxes(tickformat=".0%")
    st.plotly_chart(fig, use_container_width=True)

    opex_lines = [
        "Salaries and benefits",
        "Technology expenses",
        "Marketing expenses",
        "Rent and utilities",
        "Administrative expenses",
        "Travel expenses",
        "Professional services",
    ]
    ytd_opex = month[month["statement_line"].isin(opex_lines)][["statement_line", "ytd_amount_reporting"]]
    ytd_opex = ytd_opex.assign(v=-ytd_opex["ytd_amount_reporting"]).sort_values("v")
    fig = go.Figure(
        go.Bar(
            x=ytd_opex["v"],
            y=ytd_opex["statement_line"],
            orientation="h",
            marker_color=SERIES[1],
            hovertemplate="%{y}: €%{x:,.0f}<extra></extra>",
        )
    )
    fig = chart_layout(fig, "Operating expense breakdown (YTD)", legend=False, height=300)
    fig.update_layout(hovermode="closest")
    fig.update_xaxes(tickprefix="€", tickformat="~s", showgrid=True, gridcolor="#e9e9e9")
    fig.update_yaxes(tickprefix=None, tickformat=None)
    st.plotly_chart(fig, use_container_width=True)

    rev = pl[(pl["statement_line"] == "Total revenue") & (pl["fiscal_period"].str[:4].astype(int) >= f.fiscal_year - 1)]
    fig = go.Figure()
    for y in [f.fiscal_year - 1, f.fiscal_year]:
        d = rev[rev["fiscal_period"].str[:4].astype(int) == y]
        fig.add_bar(
            x=d["fiscal_period"].str[5:],
            y=d["amount_reporting"],
            name=str(y),
            marker_color=[SERIES[0] if y == f.fiscal_year else "#9dc8f7"][0],
        )
    st.plotly_chart(chart_layout(fig, "Revenue: actual vs previous year", height=280), use_container_width=True)

st.markdown("---")
st.markdown("##### Drill-through: statement line → general-ledger lines → source documents")
subtotal = month.set_index("statement_line")["is_subtotal"]
detail_lines = [line for line in month.sort_values("line_order")["statement_line"] if not subtotal.loc[line]]
c1, c2 = st.columns([2, 3])
line = c1.selectbox("Statement line", detail_lines, index=0)
period_choice = c2.radio("Period", ["Selected month", "Year to date"], horizontal=True)
periods = [f.fiscal_period] if period_choice == "Selected month" else f.periods_in_year
placeholders = ",".join(["?"] * len(periods))
gl = q(
    f"""select g.entity_id, g.posting_date, g.journal_id, g.journal_type, g.local_account_code, g.group_account_code,
                  g.cost_center_id, g.signed_amount_functional, g.functional_currency, g.signed_amount_reporting,
                  g.source_system, g.source_document_type, g.source_document_id, g.reference_number,
                  g.journal_description, g.ingestion_batch_id
           from finance_core.fact_general_ledger g
           where g.statement_line = ? and g.fiscal_period in ({placeholders})
             and (? = 'GROUP' or g.entity_id = ?)
           order by abs(g.signed_amount_reporting) desc limit 5000""",
    line,
    *periods,
    f.entity_id,
    f.entity_id,
)
total = -gl["signed_amount_reporting"].sum()
stmt_value = month.set_index("statement_line").loc[
    line, "amount_reporting" if period_choice == "Selected month" else "ytd_amount_reporting"
]
note = (
    "Standalone ledger lines; consolidated figures also include elimination entries."
    if f.scope == "CONSOLIDATED"
    else "Ties exactly to the statement line."
)
st.caption(
    f"{len(gl):,} ledger lines (largest first, max 5,000) · sum {money(total)} · statement {money(stmt_value)} · {note}"
)
table_with_export(
    gl,
    f"gl_drill_{line.replace(' ', '_').lower()}",
    column_config=money_columns(["signed_amount_reporting"])
    | {"signed_amount_functional": st.column_config.NumberColumn("signed_amount_functional", format="%,.2f")},
)
_ = pd, pct
