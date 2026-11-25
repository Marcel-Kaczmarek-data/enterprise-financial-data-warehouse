"""Page 13 - Data Quality & Pipeline Health."""

import plotly.graph_objects as go
import streamlit as st
from lib.data import q
from lib.ui import SERIES, STATUS, chart_layout, kpi, page_header, sidebar_filters, status_badge, table_with_export

sidebar_filters(show_scope=False)
page_header("Data Quality & Pipeline Health", "Freshness, ingestion batches, quarantine and dbt test results")

runs = q("select * from finance_audit.audit_ingestion_runs order by started_at desc")
files = q("select * from finance_audit.ingestion_file_registry")
fresh = q("select * from finance_audit.audit_source_freshness order by source_system, source_table")
tests = q("""select r.* from finance_audit.audit_dbt_node_results r
             where r.invocation_id = (select invocation_id from finance_audit.audit_dbt_node_results
                                      order by logged_at desc limit 1)""")
t = tests[tests["resource_type"] == "test"]
c = st.columns(5)
kpi(c[0], "Ingestion batches", f"{len(runs):,}", f"{int((runs['status'] != 'SUCCEEDED').sum())} failed")
kpi(c[1], "Records ingested", f"{int(runs['rows_extracted'].fillna(0).sum()):,}")
kpi(c[2], "Files received", f"{len(files):,}", f"{int((files['status'] == 'DUPLICATE').sum())} duplicates skipped")
kpi(
    c[3],
    "Quarantined",
    f"{int((files['status'] == 'QUARANTINED').sum())} files",
    f"{int(files['rows_quarantined'].fillna(0).sum())} rows rejected",
)
kpi(
    c[4],
    "dbt tests (last build)",
    f"{int((t['status'] == 'pass').sum())} / {len(t)} passed",
    f"{int((t['status'] == 'warn').sum())} warn · {int((t['status'] == 'fail').sum())} fail",
)

mismatch = int((runs["record_count_status"] == "COUNT_MISMATCH").sum())
st.markdown(
    status_badge("good" if mismatch == 0 else "critical", f"Source-to-target record counts: {mismatch} mismatches"),
    unsafe_allow_html=True,
)

left, right = st.columns(2)
by_src = runs.groupby("source_system", as_index=False)["rows_extracted"].sum().sort_values("rows_extracted")
fig = go.Figure(
    go.Bar(
        x=by_src["rows_extracted"],
        y=by_src["source_system"],
        orientation="h",
        marker_color=SERIES[0],
        hovertemplate="%{y}: %{x:,} records<extra></extra>",
    )
)
fig = chart_layout(fig, "Records processed by source system", legend=False, y_money=False)
fig.update_layout(hovermode="closest")
fig.update_xaxes(showgrid=True, gridcolor="#e9e9e9")
left.plotly_chart(fig, use_container_width=True)

dur = runs.dropna(subset=["duration_seconds"]).sort_values("duration_seconds").tail(15)
fig = go.Figure(
    go.Bar(
        x=dur["duration_seconds"],
        y=dur["source_system"] + "." + dur["source_table"],
        orientation="h",
        marker_color=SERIES[1],
        hovertemplate="%{y}: %{x:.1f}s<extra></extra>",
    )
)
fig = chart_layout(fig, "Slowest extraction batches (seconds)", legend=False, y_money=False)
fig.update_layout(hovermode="closest")
fig.update_xaxes(showgrid=True, gridcolor="#e9e9e9")
right.plotly_chart(fig, use_container_width=True)

left, right = st.columns(2)
nodes = tests.groupby(["resource_type", "status"], as_index=False).size()
fig = go.Figure()
for status, color in [
    ("pass", STATUS["good"]),
    ("success", STATUS["good"]),
    ("warn", STATUS["warning"]),
    ("fail", STATUS["critical"]),
    ("error", STATUS["critical"]),
]:
    d = nodes[nodes["status"] == status]
    if len(d):
        fig.add_bar(x=d["resource_type"], y=d["size"], name=status, marker_color=color)
fig.update_layout(barmode="stack")
left.plotly_chart(chart_layout(fig, "dbt nodes by status (last build)", y_money=False), use_container_width=True)
slow = tests[tests["resource_type"] == "model"].sort_values("execution_seconds").tail(12)
fig = go.Figure(
    go.Bar(
        x=slow["execution_seconds"],
        y=slow["node_unique_id"].str.split(".").str[-1],
        orientation="h",
        marker_color=SERIES[2],
        hovertemplate="%{y}: %{x:.2f}s<extra></extra>",
    )
)
fig = chart_layout(fig, "Slowest dbt models (seconds)", legend=False, y_money=False)
fig.update_layout(hovermode="closest")
fig.update_xaxes(showgrid=True, gridcolor="#e9e9e9")
right.plotly_chart(fig, use_container_width=True)

st.markdown("##### Source freshness")
st.dataframe(fresh, hide_index=True, use_container_width=True, height=260)
st.markdown("##### Failed and warning validations")
st.dataframe(
    t[t["status"].isin(["warn", "fail", "error"])][["node_unique_id", "status", "failures", "message"]],
    hide_index=True,
    use_container_width=True,
    height=200,
)
st.markdown("##### Ingestion batch history")
table_with_export(
    runs[
        [
            "batch_id",
            "source_system",
            "source_table",
            "extraction_mode",
            "status",
            "started_at",
            "duration_seconds",
            "rows_source",
            "rows_extracted",
            "rows_quarantined",
            "record_count_status",
            "raw_load_status",
        ]
    ],
    "ingestion_runs",
    height=320,
)
