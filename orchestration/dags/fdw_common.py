"""Shared Airflow 3 building blocks for the finance platform DAGs.

Design choices:
* Every task shells out to the same CLIs used locally (``python -m ingestion.run``, ``dbt build``,
  ``scripts/publish_reports.py``), so orchestration adds scheduling and dependencies, not logic.
* Retries with exponential backoff and per-task execution timeouts on every task.
* Asset (dataset) based scheduling chains ingestion -> raw load -> dbt layers -> marts.
* Failure callback emits a structured JSON log line (picked up by log shipping / alerting).
* Tasks are idempotent: watermarks advance only after durable writes, raw loads are keyed by
  manifest, dbt incremental models merge on unique keys - so any task can be safely re-run.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import timedelta

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import Asset

PROJECT_ROOT = os.environ.get("FDW_PROJECT_ROOT", "/opt/project")
PY = os.environ.get("FDW_PYTHON", "python")
DBT = f"cd {PROJECT_ROOT}/dbt_finance && DBT_PROFILES_DIR=. dbt"

log = logging.getLogger("fdw.airflow")

# Assets produced/consumed by the DAGs (logical data products, not physical paths).
ASSET_LANDING = {
    name: Asset(f"s3://finance-data-lake/landing/{name}")
    for name in ("erp", "crm", "banking", "payroll", "budgeting", "fx")
}
ASSET_RAW = Asset("warehouse://finance_raw")
ASSET_STAGING = Asset("warehouse://finance_staging")
ASSET_INTERMEDIATE = Asset("warehouse://finance_intermediate")
ASSET_CORE = Asset("warehouse://finance_core")
ASSET_MARTS = Asset("warehouse://finance_marts")
ASSET_PUBLISHED = Asset("warehouse://published_snapshot")


def on_failure(context) -> None:
    ti = context.get("task_instance")
    log.error(
        json.dumps(
            {
                "event": "task_failed",
                "dag_id": getattr(ti, "dag_id", None),
                "task_id": getattr(ti, "task_id", None),
                "run_id": context.get("run_id"),
                "try_number": getattr(ti, "try_number", None),
                "exception": repr(context.get("exception"))[:500],
            }
        )
    )


DEFAULT_ARGS = {
    "owner": "finance-data-engineering",
    "retries": 3,
    "retry_delay": timedelta(minutes=2),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=30),
    "execution_timeout": timedelta(minutes=60),
    "on_failure_callback": on_failure,
}


def sh(task_id: str, command: str, timeout_minutes: int = 60, **kwargs) -> BashOperator:
    return BashOperator(
        task_id=task_id,
        bash_command=f"set -euo pipefail; cd {PROJECT_ROOT}; {command}",
        execution_timeout=timedelta(minutes=timeout_minutes),
        env={"FDW_PROJECT_ROOT": PROJECT_ROOT},
        append_env=True,
        **kwargs,
    )


def dbt_build(task_id: str, selector: str, extra: str = "", timeout_minutes: int = 60, **kwargs) -> BashOperator:
    return sh(task_id, f"{DBT} build --select {selector} {extra}", timeout_minutes, **kwargs)
