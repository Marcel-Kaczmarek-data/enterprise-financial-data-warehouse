"""Finance operations DAGs.

daily_cash_position, receivables_aging_snapshot, payables_aging_snapshot, financial_forecast_refresh,
month_end_financial_close, quarter_end_consolidation, historical_backfill, warehouse_maintenance
"""

from __future__ import annotations

from datetime import datetime

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG, Param
from fdw_common import ASSET_CORE, ASSET_PUBLISHED, DBT, DEFAULT_ARGS, PY, dbt_build, sh

COMMON = {"start_date": datetime(2025, 1, 1), "catchup": False, "max_active_runs": 1, "default_args": DEFAULT_ARGS}

with DAG(
    dag_id="daily_cash_position",
    schedule="0 7 * * 1-5",
    tags=["treasury"],
    description="Bank balances, reconciliation and the cash position mart before the treasury call",
    **COMMON,
):
    bank = sh("ingest_bank_statements", f"{PY} -m ingestion.run --sources files --file-systems banking")
    load = sh("load_raw", f"{PY} -m warehouse.local.load_raw")
    cash = dbt_build("build_cash_position", "+mart_cash_position +mart_bank_reconciliation")
    bank >> load >> cash

with DAG(
    dag_id="receivables_aging_snapshot",
    schedule=ASSET_CORE,
    tags=["receivables"],
    description="Incremental as-of receivables snapshot (rebuilds the last two reporting dates)",
    **COMMON,
):
    dbt_build("build_receivables_snapshot", "fact_receivables_snapshot+")

with DAG(
    dag_id="payables_aging_snapshot",
    schedule=ASSET_CORE,
    tags=["payables"],
    description="As-of payables snapshot and aging",
    **COMMON,
):
    dbt_build("build_payables_snapshot", "fact_payables_snapshot+")

with DAG(
    dag_id="financial_forecast_refresh",
    schedule=ASSET_PUBLISHED,
    tags=["planning"],
    description="Re-score the baseline forecast (chronological backtest) after each publication",
    **COMMON,
):
    dbt_build("build_forecast", "mart_financial_forecast")

with DAG(
    dag_id="month_end_financial_close",
    schedule="0 6 1-10 * *",  # business days 1-10: soft close on BD4, close on BD8
    tags=["close"],
    description="Month-end close with explicit prerequisites; publication only when all checks pass",
    params={"fiscal_period": Param("", type="string", description="YYYY-MM; empty = previous month")},
    **COMMON,
) as close_dag:
    completeness = sh("source_completeness_check", f"{DBT} source freshness")
    full_ingest = sh("final_ingestion", f"{PY} -m ingestion.run && {PY} -m warehouse.local.load_raw")
    snapshot = sh("dbt_snapshot", f"{DBT} snapshot")
    build = dbt_build("build_and_test_all", "+mart_financial_close+ +mart_executive_financial_summary")
    critical = sh("critical_validations", f"{DBT} test --select tag:critical")
    publish = sh("publish_period_reports", f"{PY} scripts/publish_reports.py", retries=0)
    approval_note = BashOperator(
        task_id="await_controller_approval",
        bash_command="echo 'Period close approval is recorded in the ERP (period_status_changes); "
        "the close mart shows approver and timestamp.'",
    )
    completeness >> full_ingest >> snapshot >> build >> critical >> publish >> approval_note

with DAG(
    dag_id="quarter_end_consolidation",
    schedule="0 8 10 1,4,7,10 *",
    tags=["consolidation"],
    description="Quarter-end consolidation pack: translation, eliminations, consolidated statements",
    **COMMON,
):
    cons = dbt_build(
        "build_consolidation",
        "+int_intercompany_eliminations+ mart_profit_and_loss mart_balance_sheet "
        "mart_cash_flow mart_intercompany_reconciliation",
    )
    gate = sh("publication_gate", f"{PY} scripts/publish_reports.py", retries=0)
    cons >> gate

with DAG(
    dag_id="historical_backfill",
    schedule=None,
    tags=["backfill"],
    description="Controlled reprocessing: full refresh of the GL fact and dependants, then publication gate",
    params={"reason": Param("backdated correction", type="string")},
    **COMMON,
):
    refresh = dbt_build(
        "full_refresh_gl_and_dependants", "fact_general_ledger+", extra="--full-refresh", timeout_minutes=180
    )
    gate = sh("publication_gate", f"{PY} scripts/publish_reports.py", retries=0)
    refresh >> gate

with DAG(
    dag_id="warehouse_maintenance",
    schedule="0 3 * * 0",
    tags=["maintenance"],
    description="DuckDB checkpoint, dbt artifact cleanup and test-failure table pruning",
    **COMMON,
):
    sh(
        "checkpoint_warehouse",
        f"{PY} -c \"import duckdb; c=duckdb.connect('warehouse/local/finance.duckdb'); "
        "c.execute('CHECKPOINT'); c.close()\"",
    )
    sh("clean_dbt_artifacts", f"{DBT} clean")
