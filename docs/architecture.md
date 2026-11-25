# Architecture

## Data flow

```mermaid
flowchart LR
    subgraph Sources["Simulated source systems (deterministic generator, seed 20250101)"]
        ERP[(ERP<br/>PostgreSQL 16<br/>31 tables)]
        CRM[CRM REST API<br/>keyset pagination]
        FILES[File drops<br/>bank CSV/JSON · payroll CSV<br/>budget XLSX · FX CSV]
    end

    subgraph Ingestion["Python ingestion (ingestion/)"]
        PG[Incremental extract<br/>watermark updated_at+pk<br/>120 min overlap]
        API[API extract<br/>retry + backoff]
        FI[File ingest<br/>SHA-256 dedupe<br/>row quarantine]
        STATE[(Ingestion state<br/>watermarks · batches<br/>file registry)]
    end

    S3[(S3-compatible landing zone<br/>SeaweedFS locally · S3 in cloud<br/>Parquet + manifests)]

    subgraph Warehouse["Warehouse (DuckDB locally · Snowflake in cloud)"]
        RAW[finance_raw<br/>idempotent manifest loader]
        STG[finance_staging<br/>generated from contracts]
        INT[finance_intermediate<br/>FX · translation · eliminations<br/>matching · reconciliations]
        CORE[finance_core<br/>SCD2 dims · facts]
        MARTS[finance_marts<br/>17 marts]
        AUDIT[finance_audit<br/>runs · freshness · publications]
    end

    GATE{Publication gate<br/>critical tests pass?}
    PUB[(Published snapshot<br/>read-only, fingerprinted)]
    DASH[Streamlit CFO dashboard<br/>13 pages]
    PBI[Power BI<br/>specification only]

    ERP --> PG --> S3
    CRM --> API --> S3
    FILES --> FI --> S3
    PG & API & FI <--> STATE
    S3 --> RAW --> STG --> INT --> CORE --> MARTS --> GATE
    STATE -.-> AUDIT
    GATE -- yes --> PUB --> DASH
    PUB -.-> PBI
    GATE -- no --> BLOCK[Publication blocked<br/>previous snapshot stays live]
```

## Layers

| Layer | Schema | What happens there |
|---|---|---|
| Landing | S3 `landing/` | Immutable Parquet batches + a JSON manifest per batch (row count, checksum, watermark range). Rejected rows go to `quarantine/`. |
| Raw | `finance_raw` | One table per source table, loaded once per manifest (checksum verified, `raw_load_history`). Re-running is a no-op. |
| Staging | `finance_staging` | Generated from the data contracts: typing, renaming, latest-version dedupe, ingestion lineage columns. |
| Intermediate | `finance_intermediate` | Business logic: FX rate selection, account mapping, trial balance, currency translation, intercompany matching and eliminations, bank and three-way matching, subledger reconciliation, settlement events for as-of aging. |
| Core | `finance_core` | Kimball star schema. SCD2: `dim_customer` (CRM history), `dim_employee` (job history), `dim_vendor` (dbt snapshot). `fact_general_ledger` is incremental (delete+insert on DuckDB, merge on Snowflake, 45-day lookback for late postings). |
| Marts | `finance_marts` | Statements (P&L, balance sheet, cash flow, trial balance), working capital, budget, forecast, revenue, departments, reconciliations, exceptions, close status, executive summary. |
| Audit | `finance_audit` | Ingestion runs, source freshness, dbt results, publication history. |

The schema names are the same in DuckDB and Snowflake. Date functions go through adapter-dispatched macros,
so the same dbt project compiles for both (`--target snowflake`).

## Orchestration (Airflow 3, `orchestration/dags`)

```mermaid
flowchart TB
    subgraph Schedules
        A1[source_erp_ingestion<br/>every 2h]
        A2[source_crm_ingestion<br/>every 2h]
        A3[source_bank_ingestion<br/>3x daily]
        A4[payroll · budget · FX<br/>calendar schedules]
    end
    A1 & A2 & A3 & A4 -->|Asset: landing batches| L[raw_warehouse_loading]
    L -->|Asset| Q[source_data_quality]
    Q -->|Asset| S[dbt_staging_transformations] --> I[dbt_intermediate_transformations]
    I --> C[dbt_core_warehouse] --> R[financial_reconciliation] --> M[dbt_financial_marts]
    M --> P[publication gate]
    MEC[month_end_financial_close<br/>BD1-BD10] -.-> M
    QEC[quarter_end_consolidation] -.-> M
```

21 DAGs, scheduled by data assets (Airflow 3 `Asset`) rather than fixed times. They are checked by
`orchestration/validate_dags.py` inside the official `apache/airflow:3.1.5-python3.12` image. All 21 import
without errors. The DAGs have **not** been run in a long-lived Airflow deployment. The local demo uses
`scripts/pipeline.py`, which runs the same commands in the same order.

## Cloud target (not deployed)

* **Snowflake**: SQL in `warehouse/snowflake/` (warehouses + resource monitor, database/schemas, RBAC with
  9 functional roles, masking and row-access policies, storage integration and stages, monitoring
  queries). **Not executed** against an account.
* **Terraform** (`infrastructure/terraform`): S3 data lake (versioned, encrypted, lifecycle rules), IAM
  roles for the pipeline and the Snowflake storage integration, and the Snowflake platform objects.
  `terraform fmt -check`, `init -backend=false` and `validate` pass. **`plan`/`apply` have never been run**,
  so nothing has been created and no cost has been incurred.
