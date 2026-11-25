"""Page 12 - Financial Close Monitoring."""

import plotly.graph_objects as go
import streamlit as st
from lib.data import q
from lib.ui import STATUS, chart_layout, kpi, page_header, pct, sidebar_filters, status_badge, table_with_export

f = sidebar_filters(show_scope=False)
page_header("Financial Close", "Period status, close-task completion, validations and approvals by subsidiary", f)

close = q(
    "select * from finance_marts.mart_financial_close where fiscal_period = ? order by entity_id", f.fiscal_period
)
latest_open = q(
    """select min(fiscal_period) p from finance_marts.mart_financial_close where period_status <> 'CLOSED'"""
)["p"].iloc[0]
c = st.columns(4)
kpi(c[0], "Current open period", latest_open or "–", "earliest period not yet closed")
kpi(
    c[1],
    "Entities closed",
    f"{int((close['period_status'] == 'CLOSED').sum())} / {len(close)}",
    f"for {f.fiscal_period}",
)
kpi(c[2], "Close task completion", pct(close["close_completion_rate"].mean()), "9 tasks per entity")
kpi(
    c[3],
    "Critical validations passed",
    f"{int(close['critical_checks_passed'].sum())} / {len(close)}",
    "journals, trial balance, AR, AP",
)

tasks = [
    "task_journals_balanced",
    "task_trial_balance",
    "task_ar_reconciled",
    "task_ap_reconciled",
    "task_bank_reconciled",
    "task_depreciation_posted",
    "task_accruals_posted",
    "task_fx_revaluation_posted",
    "task_intercompany_matched",
]
labels = [
    "Journals balanced",
    "Trial balance",
    "AR reconciled",
    "AP reconciled",
    "Bank reconciled",
    "Depreciation posted",
    "Accruals posted",
    "FX revaluation",
    "Intercompany matched",
]
z = close[tasks].values.tolist()
fig = go.Figure(
    go.Heatmap(
        z=z,
        x=labels,
        y=close["entity_id"],
        colorscale=[[0, STATUS["serious"]], [1, "#cce3fd"]],
        zmin=0,
        zmax=1,
        showscale=False,
        xgap=2,
        ygap=2,
        text=[["✓ done" if v else "✗ open" for v in row] for row in z],
        texttemplate="%{text}",
        hovertemplate="%{y} · %{x}: %{text}<extra></extra>",
    )
)
fig = chart_layout(fig, f"Close checklist by entity - {f.fiscal_period}", legend=False, y_money=False, height=520)
fig.update_layout(hovermode="closest")
fig.update_yaxes(autorange="reversed")
st.plotly_chart(fig, use_container_width=True)

left, right = st.columns([2, 3])
with left:
    st.markdown("##### Closing status by subsidiary")
    for r in close.itertuples():
        state = {"CLOSED": "good", "SOFT_CLOSED": "warning", "REOPENED": "serious", "OPEN": "warning"}[r.period_status]
        st.markdown(
            f"`{r.entity_id}` "
            + status_badge(state, f"{r.period_status.replace('_', ' ').title()} · {r.tasks_completed}/9 tasks"),
            unsafe_allow_html=True,
        )
with right:
    st.markdown("##### Pending validations and failed reconciliations")
    pend = close[close["tasks_completed"] < 9][
        [
            "entity_id",
            "period_status",
            "ar_difference",
            "ap_difference",
            "bank_exceptions",
            "ic_mismatches",
            "draft_journals",
        ]
    ]
    st.dataframe(pend, hide_index=True, use_container_width=True, height=300)
    st.markdown("##### Report publication history")
    pubs = q("""select publication_id, published_at, status, fingerprint, latest_period, critical_test_failures,
                       open_critical_exceptions from finance_audit.audit_report_publications order by published_at desc""")
    st.dataframe(pubs, hide_index=True, use_container_width=True, height=180)

st.markdown("##### Period status change history (approvals, reopen events)")
hist = q(
    """select entity_id, fiscal_period, from_status, to_status, changed_at, changed_by, reason
            from finance_staging.stg_erp__period_status_changes
            where fiscal_period >= ? order by changed_at desc""",
    f"{f.fiscal_year - 1}-01",
)
table_with_export(hist, "period_status_history", height=300)
