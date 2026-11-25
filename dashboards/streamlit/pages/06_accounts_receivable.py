"""Page 6 - Accounts Receivable (historical as-of aging)."""

import plotly.graph_objects as go
import streamlit as st
from lib.data import q
from lib.ui import SERIES, chart_layout, kpi, money, money_columns, page_header, pct, sidebar_filters, table_with_export

f = sidebar_filters()
page_header(
    "Accounts Receivable", "As-of aging: invoices paid after the reporting date still show as open on that date", f
)

snap = q(
    """select max(snapshot_date) d from finance_core.fact_receivables_snapshot where fiscal_period = ?""",
    f.fiscal_period,
)["d"].iloc[0]
open_items = q(
    """select s.*, c.customer_name from finance_core.fact_receivables_snapshot s
                  left join finance_core.dim_customer c on s.customer_key = c.customer_key
                  where s.snapshot_date = ? and not s.is_intercompany and (? = 'GROUP' or s.entity_id = ?)""",
    snap,
    f.entity_id,
    f.entity_id,
)
aging = q(
    """with per_entity as (
                 select snapshot_date, fiscal_period, entity_id, max(total_outstanding_reporting) outstanding,
                        max(revenue_trailing_3m) rev3m
                 from finance_marts.mart_receivables_aging where (? = 'GROUP' or entity_id = ?) group by 1, 2, 3)
             select snapshot_date, fiscal_period, sum(outstanding) outstanding, sum(rev3m) rev3m
             from per_entity group by 1, 2 order by 1""",
    f.entity_id,
    f.entity_id,
)
total = open_items["outstanding_amount_reporting"].sum()
overdue = open_items.loc[open_items["is_overdue"], "outstanding_amount_reporting"].sum()
cur = aging[aging["snapshot_date"] == snap]
dso = (cur["outstanding"].iloc[0] * 91 / cur["rev3m"].iloc[0]) if len(cur) and cur["rev3m"].iloc[0] else None

c = st.columns(4)
kpi(c[0], "Total receivables", money(total), f"as of {snap}")
kpi(
    c[1],
    "Overdue receivables",
    money(overdue),
    f"{pct(overdue / total)} of total" if total else None,
    delta_good=(overdue / total) < 0.25 if total else None,
)
kpi(c[2], "Open invoices", f"{len(open_items):,}", f"{int(open_items['is_overdue'].sum()):,} overdue")
kpi(c[3], "Days sales outstanding", f"{dso:.0f} days" if dso else "–", "receivables / trailing 3m revenue × 91")

left, right = st.columns(2)
buckets = open_items.groupby(["aging_bucket_order", "aging_bucket"], as_index=False)[
    "outstanding_amount_reporting"
].sum()
fig = go.Figure(
    go.Bar(
        x=buckets["aging_bucket"],
        y=buckets["outstanding_amount_reporting"],
        marker_color=["#84b9f3", "#519ced", "#257de0", "#2370cd", "#1757ac", "#0e3d7e"][: len(buckets)],
        hovertemplate="%{x}: €%{y:,.0f}<extra></extra>",
    )
)
left.plotly_chart(chart_layout(fig, f"Aging bucket distribution at {snap}", legend=False), use_container_width=True)

trend = aging[aging["snapshot_date"] <= snap].tail(24).copy()
trend["dso"] = trend["outstanding"] * 91 / trend["rev3m"]
fig = go.Figure(
    go.Scatter(
        x=trend["fiscal_period"],
        y=trend["dso"],
        mode="lines+markers",
        name="DSO",
        line={"color": SERIES[0], "width": 2},
        marker={"size": 8},
        hovertemplate="%{x}: %{y:.0f} days<extra></extra>",
    )
)
fig = chart_layout(fig, "Days sales outstanding (monthly, historical as-of)", y_money=False, legend=False)
right.plotly_chart(fig, use_container_width=True)

left, right = st.columns(2)
top = (
    open_items.groupby("customer_name", as_index=False)["outstanding_amount_reporting"]
    .sum()
    .sort_values("outstanding_amount_reporting")
    .tail(12)
)
fig = go.Figure(
    go.Bar(
        x=top["outstanding_amount_reporting"],
        y=top["customer_name"],
        orientation="h",
        marker_color=SERIES[0],
        hovertemplate="%{y}: €%{x:,.0f}<extra></extra>",
    )
)
fig = chart_layout(fig, "Largest outstanding balances by customer", legend=False, height=380)
fig.update_layout(hovermode="closest")
fig.update_xaxes(tickprefix="€", tickformat="~s", showgrid=True, gridcolor="#e9e9e9")
fig.update_yaxes(tickprefix=None, tickformat=None)
left.plotly_chart(fig, use_container_width=True)

perf = q(
    """select customer_segment_at_invoice segment, avg(days_paid_after_due) avg_days_late,
                   avg(days_to_pay) avg_days_to_pay, count(*) invoices
            from finance_core.fact_customer_invoices
            where not is_intercompany and days_to_pay is not null and fiscal_period like ? || '%'
              and (? = 'GROUP' or entity_id = ?) group by 1 order by 1""",
    str(f.fiscal_year),
    f.entity_id,
    f.entity_id,
)
fig = go.Figure()
fig.add_bar(x=perf["segment"], y=perf["avg_days_to_pay"], name="Average days to pay", marker_color=SERIES[0])
fig.add_bar(x=perf["segment"], y=perf["avg_days_late"], name="Average days after due date", marker_color=SERIES[1])
right.plotly_chart(
    chart_layout(fig, "Collection performance by customer segment (paid invoices)", y_money=False, height=380),
    use_container_width=True,
)

st.markdown("##### Invoice-level drill-down (open at reporting date)")
cols = [
    "invoice_number",
    "entity_id",
    "customer_name",
    "customer_segment_at_invoice",
    "invoice_date",
    "due_date",
    "days_overdue",
    "aging_bucket",
    "currency",
    "invoice_amount",
    "outstanding_amount",
    "outstanding_amount_reporting",
]
table_with_export(
    open_items.sort_values("days_overdue", ascending=False)[cols],
    "open_receivables",
    column_config=money_columns(["outstanding_amount_reporting"]),
)
