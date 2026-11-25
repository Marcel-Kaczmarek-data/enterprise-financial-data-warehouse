"""Import every DAG with Airflow's DagBag and fail on import errors or missing expected DAGs.

python orchestration/validate_dags.py        (requires apache-airflow; used in CI)
"""

from __future__ import annotations

import sys
from pathlib import Path

EXPECTED = {
    "source_erp_ingestion",
    "source_crm_ingestion",
    "source_bank_ingestion",
    "source_payroll_ingestion",
    "source_budget_ingestion",
    "source_exchange_rate_ingestion",
    "raw_warehouse_loading",
    "source_data_quality",
    "dbt_staging_transformations",
    "dbt_intermediate_transformations",
    "dbt_core_warehouse",
    "financial_reconciliation",
    "dbt_financial_marts",
    "daily_cash_position",
    "receivables_aging_snapshot",
    "payables_aging_snapshot",
    "financial_forecast_refresh",
    "month_end_financial_close",
    "quarter_end_consolidation",
    "historical_backfill",
    "warehouse_maintenance",
}


def main() -> int:
    from airflow.models.dagbag import DagBag

    dags_dir = Path(__file__).resolve().parent / "dags"
    sys.path.insert(0, str(dags_dir))
    bag = DagBag(dag_folder=str(dags_dir), include_examples=False)
    if bag.import_errors:
        for f, err in bag.import_errors.items():
            print(f"IMPORT ERROR {f}:\n{err}")
        return 1
    missing = EXPECTED - set(bag.dag_ids)
    if missing:
        print(f"missing DAGs: {sorted(missing)}")
        return 1
    for dag_id in sorted(bag.dag_ids):
        dag = bag.dags[dag_id]  # in-memory; get_dag() would query the metadata DB
        print(f"OK {dag_id:36s} tasks={len(dag.tasks):2d} schedule={dag.timetable.summary}")
    print(f"{len(bag.dag_ids)} DAGs imported without errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
