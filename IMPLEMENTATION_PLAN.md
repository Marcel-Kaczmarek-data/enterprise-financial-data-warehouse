# Implementation plan and status

The status words mean:

* **Implemented and tested**: the code exists and has run end to end on the local stack with automated checks.
* **Implemented and validated**: the code exists and passed static or import validation, but has not been run for real.
* **Written, not executed**: code or SQL for a cloud service that has not been run against that service.
* **Specification**: documentation only.
* **Not started**.

## Phases

| # | Phase | Status | Evidence |
|---|---|---|---|
| 1 | Repository foundation, configuration, financial rules | Implemented and tested | `config/`, `pyproject.toml`, `finance_common/` with unit tests |
| 2 | Deterministic double-entry data generator | Implemented and tested | `data_generator/`, `tests/unit/test_ledger.py`, `tests/financial/` |
| 3 | Simulated source systems (ERP Postgres, CRM API, file drops) | Implemented and tested | `source_systems/`, used by every demo run |
| 4 | Data contracts | Implemented and tested | `finance_common/contracts.py`, `docs/data-contracts.md` (generated) |
| 5 | Ingestion: incremental DB extract, API, files, state | Implemented and tested | `ingestion/`, measured run in README |
| 6 | Landing zone and idempotent raw load | Implemented and tested | `warehouse/local/load_raw.py`, `tests/end_to_end/test_idempotency.py` |
| 7 | dbt staging (generated) and intermediate logic | Implemented and tested | 44 staging + 17 intermediate models, dbt tests |
| 8 | Core star schema, SCD2, incremental GL | Implemented and tested | 25 core models, `snapshots/snap_erp__vendors.sql` |
| 9 | Multi-currency translation and consolidation | Implemented and tested | `intermediate/consolidation/`, financial singular tests |
| 10 | Reconciliation (bank, three-way, intercompany, subledger) | Implemented and tested | `intermediate/reconciliation/`, `tests/integration/` |
| 11 | Financial marts and exceptions | Implemented and tested | 17 marts |
| 12 | Period close and publication gate | Implemented and tested | `scripts/publish_reports.py`, `tests/end_to_end/test_golden_scenarios.py` |
| 13 | Streamlit CFO dashboard (13 pages) | Implemented and tested | `scripts/capture_screenshots.py` renders every page and fails on any exception |
| 14 | Airflow orchestration (21 DAGs) | Implemented and validated | Import check in `apache/airflow:3.1.5-python3.12`. Not run on a scheduler |
| 15 | Snowflake platform SQL (RBAC, masking, row access, stages, monitors) | Written, not executed | `warehouse/snowflake/` |
| 16 | Terraform (S3, IAM, Snowflake) | Implemented and validated | `fmt -check`, `init -backend=false` and `validate` pass in `hashicorp/terraform:1.9.8`. Never planned or applied |
| 17 | CI/CD | Implemented, not yet run on GitHub | `.github/workflows/ci.yml`. Each step was run locally |
| 18 | Documentation | Done | README, `docs/`, ADRs |
| – | Power BI | Specification | `dashboards/powerbi/` (model + DAX, no PBIX) |
| – | Prometheus / Grafana | Not started | Observability today: `finance_audit` schema and the Data Quality page |
| – | Great Expectations | Not started | Contract validation in ingestion and dbt tests cover the same checks |

## Known limitations

* **Cash accumulates.** The holding company pays a dividend only from its own standalone profit. Group cash
  therefore grows to about EUR 218M by 2025-11, and the current ratio is unrealistically high (about 15).
  Fix: dividends paid up from the subsidiaries to the parent (with an intercompany-dividend elimination)
  and a group payout policy.
* **CRM and file ingestion are sequential.** They take about 9 and 13 minutes on the development profile.
  Pages and files can be fetched in parallel. The audit trail would need per-worker batch ids.
* **Cash-flow forecast.** The growth-adjusted seasonal-naive baseline has a WAPE of 0.76 on operating
  cash flow. A driver-based forecast (AR/AP run-off plus tax calendar) would fit better.
* **Snowflake** has not been tested against a real account: the dbt compile, the SQL scripts and the
  Terraform provider resources are unverified.
* **Airflow** DAGs are import-validated only. The local demo runs the same commands through `scripts/pipeline.py`.
* Minority interests, hyperinflation accounting and multi-level ownership below 100% are out of scope.
  All subsidiaries are wholly owned.

## Next steps (in priority order)

1. Run the GitHub Actions workflow on the first push and fix anything that differs from local runs.
2. Intra-group dividends and a payout policy (realistic cash and current ratio).
3. Parallel CRM and file ingestion, with a benchmark before and after (`benchmarks/run_benchmarks.py`).
4. Snowflake trial account: `dbt build --target snowflake`, then compare row counts and fingerprints with DuckDB.
5. Prometheus metrics from the pipeline runner and a Grafana dashboard.
