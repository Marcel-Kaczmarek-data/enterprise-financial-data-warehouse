"""Source ingestion DAGs: one per source system, each publishing a landing-zone asset.

source_erp_ingestion, source_crm_ingestion, source_bank_ingestion, source_payroll_ingestion,
source_budget_ingestion, source_exchange_rate_ingestion
"""

from __future__ import annotations

from datetime import datetime

from airflow.sdk import DAG
from fdw_common import ASSET_LANDING, DEFAULT_ARGS, PY, sh

SOURCES = [
    # dag_id, asset, ingestion arguments, schedule, description
    (
        "source_erp_ingestion",
        "erp",
        "--sources erp",
        "15 */2 * * *",
        "Incremental ERP extraction (composite watermark + overlap) from PostgreSQL",
    ),
    (
        "source_crm_ingestion",
        "crm",
        "--sources crm",
        "30 */2 * * *",
        "CRM REST API extraction with cursor pagination and retries",
    ),
    (
        "source_bank_ingestion",
        "banking",
        "--sources files --file-systems banking",
        "0 6,12,18 * * *",
        "Bank statements (CSV) and balances (JSON) with checksum duplicate detection",
    ),
    (
        "source_payroll_ingestion",
        "payroll",
        "--sources files --file-systems payroll",
        "0 4 26-31 * *",
        "Monthly payroll results, employees and expense claims",
    ),
    (
        "source_budget_ingestion",
        "budgeting",
        "--sources files --file-systems budgeting",
        "0 5 * * 1",
        "Budget / forecast workbooks (Excel)",
    ),
    (
        "source_exchange_rate_ingestion",
        "fx",
        "--sources files --file-systems fx",
        "30 17 * * 1-5",
        "Provider exchange rates after the daily fixing (offline fixtures in the local environment)",
    ),
]

for dag_id, asset_name, args, schedule, description in SOURCES:
    with DAG(
        dag_id=dag_id,
        description=description,
        schedule=schedule,
        start_date=datetime(2025, 1, 1),
        catchup=False,
        max_active_runs=1,
        default_args=DEFAULT_ARGS,
        tags=["ingestion", asset_name],
    ) as dag:
        sh(
            "extract_to_landing",
            f"{PY} -m ingestion.run {args}",
            timeout_minutes=45,
            outlets=[ASSET_LANDING[asset_name]],
        )
    globals()[dag_id] = dag
