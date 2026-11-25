"""Page 7 - Accounts Payable."""

import plotly.graph_objects as go
import streamlit as st
from lib.data import q
from lib.ui import SERIES, chart_layout, kpi, money, money_columns, page_header, pct, sidebar_filters, table_with_export

f = sidebar_filters()
page_header("Accounts Payable", "Outstanding supplier liabilities, payment schedule and supplier spend", f)

snap = q(
    "select max(snapshot_date) d from finance_core.fact_payables_snapshot where fiscal_period = ?", f.fiscal_period
)["d"].iloc[0]
items = q(
    """select * from finance_core.fact_payables_snapshot
             where snapshot_date = ? and not is_intercompany and (? = 'GROUP' or entity_id = ?)""",
    snap,
    f.entity_id,
    f.entity_id,
)
aging = q(
    """with per_entity as (
                 select snapshot_date, fiscal_period, entity_id, max(total_outstanding_reporting) outstanding,
                        max(purchases_trailing_3m) p3m
                 from finance_marts.mart_payables_aging where (? = 'GROUP' or entity_id = ?) group by 1, 2, 3)
             select snapshot_date, fiscal_period, sum(outstanding) outstanding, sum(p3m) p3m
             from per_entity group by 1, 2 order by 1""",
    f.entity_id,
    f.entity_id,
)
total = items["outstanding_amount_reporting"].sum()
overdue = items.loc[items["is_overdue"], "outstanding_amount_reporting"].sum()
upcoming = items.loc[(items["days_overdue"] >= -14) & ~items["is_overdue"], "outstanding_amount_reporting"].sum()
cur = aging[aging["snapshot_date"] == snap]
dpo = cur["outstanding"].iloc[0] * 91 / cur["p3m"].iloc[0] if len(cur) and cur["p3m"].iloc[0] else None
discounts = q(
    """select sum(discount_taken) d from finance_core.fact_vendor_invoices
                 where fiscal_period like ? || '%' and (? = 'GROUP' or entity_id = ?)""",
    str(f.fiscal_year),
    f.entity_id,
    f.entity_id,
)["d"].iloc[0]

c = st.columns(4)
kpi(c[0], "Total payables", money(total), f"as of {snap}")
kpi(c[1], "Overdue supplier invoices", money(overdue), f"{pct(overdue / total)} of total" if total else None)
kpi(c[2], "Due in next 14 days", money(upcoming), "payment run planning")
kpi(
    c[3],
    "Days payable outstanding",
    f"{dpo:.0f} days" if dpo else "–",
    f"early-payment discounts {money(discounts or 0)} (txn ccy)",
)

left, right = st.columns(2)
b = items.groupby(["aging_bucket_order", "aging_bucket"], as_index=False)["outstanding_amount_reporting"].sum()
fig = go.Figure(
    go.Bar(
        x=b["aging_bucket"],
        y=b["outstanding_amount_reporting"],
        marker_color=["#ffd2b9", "#f9b38e", "#f47230", "#d95f20", "#b74e17", "#8f3c10"][: len(b)],
        hovertemplate="%{x}: €%{y:,.0f}<extra></extra>",
    )
)
left.plotly_chart(chart_layout(fig, f"Payables aging at {snap}", legend=False), use_container_width=True)

sched = items[items["days_overdue"] <= 0].copy()
sched["week"] = (-(sched["days_overdue"]) // 7).clip(upper=8)
w = sched.groupby("week", as_index=False)["outstanding_amount_reporting"].sum()
w["label"] = w["week"].apply(lambda x: f"Week +{int(x) + 1}" if x < 8 else "Later")
fig = go.Figure(
    go.Bar(
        x=w["label"],
        y=w["outstanding_amount_reporting"],
        marker_color=SERIES[1],
        hovertemplate="%{x}: €%{y:,.0f}<extra></extra>",
    )
)
right.plotly_chart(
    chart_layout(fig, "Payment schedule by due week (not yet due)", legend=False), use_container_width=True
)

spend = q(
    """select vendor_name, vendor_category, sum(spend_reporting) spend, sum(invoices) invoices,
                    sum(invoices_paid_late) paid_late, avg(avg_days_to_pay) avg_days_to_pay
             from finance_marts.mart_supplier_spend
             where fiscal_period between ? and ? and (? = 'GROUP' or entity_id = ?)
             group by 1, 2 order by spend desc""",
    f.periods_in_year[0],
    f.fiscal_period,
    f.entity_id,
    f.entity_id,
)
left, right = st.columns(2)
top = spend.head(12).sort_values("spend")
fig = go.Figure(
    go.Bar(
        x=top["spend"],
        y=top["vendor_name"],
        orientation="h",
        marker_color=SERIES[1],
        hovertemplate="%{y}: €%{x:,.0f}<extra></extra>",
    )
)
fig = chart_layout(fig, "Top suppliers by spend (YTD)", legend=False, height=380)
fig.update_layout(hovermode="closest")
fig.update_xaxes(tickprefix="€", tickformat="~s", showgrid=True, gridcolor="#e9e9e9")
fig.update_yaxes(tickprefix=None, tickformat=None)
left.plotly_chart(fig, use_container_width=True)
cat = spend.groupby("vendor_category", as_index=False)["spend"].sum().sort_values("spend", ascending=False)
share_top10 = spend.head(10)["spend"].sum() / spend["spend"].sum() if len(spend) else 0
fig = go.Figure(
    go.Bar(
        x=cat["vendor_category"],
        y=cat["spend"],
        marker_color=SERIES[2],
        hovertemplate="%{x}: €%{y:,.0f}<extra></extra>",
    )
)
right.plotly_chart(
    chart_layout(
        fig, f"Spend by category · top-10 supplier concentration {pct(share_top10)}", legend=False, height=380
    ),
    use_container_width=True,
)

st.markdown("##### Supplier invoice drill-down (open at reporting date)")
cols = [
    "vendor_invoice_number",
    "entity_id",
    "vendor_name",
    "vendor_category",
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
    items.sort_values("due_date")[cols], "open_payables", column_config=money_columns(["outstanding_amount_reporting"])
)
