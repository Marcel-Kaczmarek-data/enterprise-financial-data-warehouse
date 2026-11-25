# ADR 0005: Data contracts as the single schema definition

**Status:** accepted

## Context
The same 44 source tables are described in many places: generator output, PostgreSQL DDL, ingestion
validation, dbt sources and staging, and documentation. Keeping them in sync by hand drifts.

## Decision
`finance_common/contracts.py` defines each table once (columns, logical types, primary key, mutability,
watermark, delivery, sensitivity). Code generates the rest: Arrow schemas, Postgres DDL, dbt staging SQL
and YAML (`scripts/generate_dbt_staging.py`), and `docs/data-contracts.md`
(`scripts/generate_contract_docs.py`).

## Consequences
* A schema change is one edit plus regeneration. Ingestion rejects data that breaks the contract.
* Sensitive columns (`PII`, `FINANCIAL_ACCOUNT`, `PAYROLL`) are classified at the source, which drives
  the Snowflake masking policies.
