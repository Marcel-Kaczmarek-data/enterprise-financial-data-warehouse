"""Page 10 - Financial Consolidation."""

import plotly.graph_objects as go
import streamlit as st
from lib.data import q
from lib.ui import SERIES, chart_layout, kpi, money, money_columns, page_header, sidebar_filters, table_with_export

f = sidebar_filters(show_scope=False)
page_header("Financial Consolidation", "From standalone statements to group: translation, eliminations, CTA", f)

periods = f.periods_in_year
ph = ",".join(["?"] * len(periods))
bridge = q(
    f"""
    with standalone as (
        select statement_line, line_order, sum(amount_reporting) standalone
        from finance_marts.mart_profit_and_loss where reporting_scope = 'STANDALONE' and fiscal_period in ({ph})
        group by 1, 2),
    consolidated as (
        select statement_line, sum(amount_reporting) consolidated
        from finance_marts.mart_profit_and_loss where reporting_scope = 'CONSOLIDATED' and fiscal_period in ({ph})
        group by 1)
    select s.statement_line, s.line_order, s.standalone, c.consolidated - s.standalone eliminations, c.consolidated
    from standalone s join consolidated c using (statement_line) order by s.line_order""",
    *periods,
    *periods,
)
elim = q(f"""select * from finance_marts.mart_intercompany_reconciliation where fiscal_period in ({ph})""", *periods)
ic_rev = elim.loc[elim["elimination_type"] == "IC_REVENUE_EXPENSE", "side_a_amount"].sum()
cta = q(
    """select sum(amount_reporting) c from finance_marts.mart_balance_sheet where reporting_scope = 'CONSOLIDATED'
           and fiscal_period = ? and statement_line = 'Currency translation adjustments'""",
    f.fiscal_period,
)["c"].iloc[0]
np_ = bridge.set_index("statement_line")
c = st.columns(4)
kpi(c[0], "Standalone net profit (sum)", money(np_.loc["Net profit", "standalone"]))
kpi(
    c[1],
    "Consolidated net profit",
    money(np_.loc["Net profit", "consolidated"]),
    "eliminations do not change group profit",
)
kpi(c[2], "Intercompany revenue eliminated YTD", money(-ic_rev))
kpi(c[3], "Currency translation adjustment", money(cta), f"equity at {f.fiscal_period}")

st.markdown("##### Consolidation bridge YTD: standalone sum → eliminations → consolidated (EUR)")
st.dataframe(
    bridge.drop(columns=["line_order"])
    .rename(
        columns={
            "statement_line": "Line",
            "standalone": "Standalone (sum)",
            "eliminations": "Eliminations",
            "consolidated": "Consolidated",
        }
    )
    .style.format(dict.fromkeys(["Standalone (sum)", "Eliminations", "Consolidated"], "€{:,.0f}")),
    hide_index=True,
    use_container_width=True,
    height=560,
)

left, right = st.columns(2)
standalone = q(
    """select entity_id, sum(amount_reporting) net_profit from finance_marts.mart_profit_and_loss
                  where reporting_scope = 'STANDALONE' and statement_line = 'Net profit' and fiscal_period between ? and ?
                  group by 1 order by 2""",
    periods[0],
    f.fiscal_period,
)
fig = go.Figure(
    go.Bar(
        x=standalone["net_profit"],
        y=standalone["entity_id"],
        orientation="h",
        marker_color=SERIES[0],
        hovertemplate="%{y}: €%{x:,.0f}<extra></extra>",
    )
)
fig = chart_layout(fig, "Standalone net profit by entity (YTD, EUR)", legend=False, height=420)
fig.update_layout(hovermode="closest")
fig.update_xaxes(tickprefix="€", tickformat="~s", showgrid=True, gridcolor="#e9e9e9")
fig.update_yaxes(tickprefix=None, tickformat=None)
left.plotly_chart(fig, use_container_width=True)

cta_e = q(
    """select entity_id, closing_balance_reporting cta from finance_intermediate.int_translated_trial_balance
             where group_account_code = '3200' and fiscal_period = ? and closing_balance_reporting <> 0 order by 2""",
    f.fiscal_period,
)
cta_e["cta"] = -cta_e["cta"]
fig = go.Figure(
    go.Bar(
        x=cta_e["cta"],
        y=cta_e["entity_id"],
        orientation="h",
        marker_color=[SERIES[0] if v >= 0 else SERIES[1] for v in cta_e["cta"]],
        hovertemplate="%{y}: €%{x:,.0f}<extra></extra>",
    )
)
fig = chart_layout(fig, "Currency translation adjustment by non-EUR entity (equity, EUR)", legend=False, height=420)
fig.update_layout(hovermode="closest")
fig.update_xaxes(tickprefix="€", tickformat="~s", showgrid=True, gridcolor="#e9e9e9")
fig.update_yaxes(tickprefix=None, tickformat=None)
right.plotly_chart(fig, use_container_width=True)

st.markdown("##### Intercompany positions and elimination entries (selected period)")
cur = elim[elim["fiscal_period"] == f.fiscal_period]
table_with_export(
    cur[
        [
            "elimination_type",
            "side_a_entity",
            "side_b_entity",
            "side_a_amount",
            "side_b_amount",
            "elimination_difference",
            "difference_pct",
            "reconciliation_status",
        ]
    ],
    "intercompany_eliminations",
    height=320,
    column_config=money_columns(["side_a_amount", "side_b_amount", "elimination_difference"]),
)
st.caption(
    "Scope: wholly owned subsidiaries (full consolidation). Differences on IC revenue/expense are reclassified "
    "to 'Other non-operating items'; balance differences are held in an elimination suspense account."
)
