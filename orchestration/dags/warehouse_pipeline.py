"""Warehouse DAGs chained by assets: raw load -> dbt layers -> quality -> reconciliation -> marts -> publish.

raw_warehouse_loading, source_data_quality, dbt_staging_transformations,
dbt_intermediate_transformations, dbt_core_warehouse, financial_reconciliation, dbt_financial_marts
The marts DAG ends with the publication gate: if any CRITICAL test failed, publication is blocked and
the task fails (downstream consumers keep the previous validated snapshot).
"""

from __future__ import annotations

import operator
from datetime import datetime
from functools import reduce

from airflow.sdk import DAG
from fdw_common import (
    ASSET_CORE,
    ASSET_INTERMEDIATE,
    ASSET_LANDING,
    ASSET_MARTS,
    ASSET_PUBLISHED,
    ASSET_RAW,
    ASSET_STAGING,
    DBT,
    DEFAULT_ARGS,
    PY,
    dbt_build,
    sh,
)

COMMON = {"start_date": datetime(2025, 1, 1), "catchup": False, "max_active_runs": 1, "default_args": DEFAULT_ARGS}

# Runs whenever ANY source lands a new batch (asset OR-condition).
with DAG(
    dag_id="raw_warehouse_loading",
    schedule=reduce(operator.or_, ASSET_LANDING.values()),
    description="Load committed landing manifests into finance_raw (idempotent, checksum-verified)",
    tags=["warehouse"],
    **COMMON,
):
    sh("load_raw", f"{PY} -m warehouse.local.load_raw", outlets=[ASSET_RAW])

with DAG(
    dag_id="source_data_quality",
    schedule=ASSET_RAW,
    tags=["quality"],
    description="Source freshness and staging contract tests (blocking on errors)",
    **COMMON,
):
    freshness = sh("source_freshness", f"{DBT} source freshness")
    contracts = sh("staging_contract_tests", f"{DBT} test --select staging")
    freshness >> contracts

with DAG(
    dag_id="dbt_staging_transformations",
    schedule=ASSET_RAW,
    tags=["dbt"],
    description="Staging models (normalisation, dedupe, lineage) + tests",
    **COMMON,
):
    dbt_build("dbt_build_staging", "staging seeds", outlets=[ASSET_STAGING])

with DAG(
    dag_id="dbt_intermediate_transformations",
    schedule=ASSET_STAGING,
    tags=["dbt"],
    description="FX, GL enrichment, settlements, matching engines",
    **COMMON,
):
    dbt_build("dbt_build_intermediate", "intermediate.fx intermediate.finance", outlets=[ASSET_INTERMEDIATE])

with DAG(
    dag_id="dbt_core_warehouse",
    schedule=ASSET_INTERMEDIATE,
    tags=["dbt"],
    description="Snapshots (SCD2), dimensions and incremental facts",
    **COMMON,
):
    snap = sh("dbt_snapshot", f"{DBT} snapshot")
    core = dbt_build(
        "dbt_build_core",
        "core intermediate.receivables intermediate.payables intermediate.consolidation "
        "intermediate.treasury intermediate.planning",
        outlets=[ASSET_CORE],
    )
    snap >> core

with DAG(
    dag_id="financial_reconciliation",
    schedule=ASSET_CORE,
    tags=["reconciliation"],
    description="Bank, subledger, intercompany and three-way reconciliation engines",
    **COMMON,
):
    dbt_build(
        "dbt_build_reconciliation",
        "intermediate.reconciliation mart_intercompany_reconciliation mart_bank_reconciliation",
    )

with DAG(
    dag_id="dbt_financial_marts",
    schedule=ASSET_CORE,
    tags=["dbt", "publication"],
    description="Financial statements and analytics marts, then the publication gate",
    **COMMON,
):
    marts = dbt_build("dbt_build_marts", "marts audit", outlets=[ASSET_MARTS])
    publish = sh("publication_gate", f"{PY} scripts/publish_reports.py", outlets=[ASSET_PUBLISHED], retries=0)
    marts >> publish
