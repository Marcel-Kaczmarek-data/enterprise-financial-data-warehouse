# ADR 0001: DuckDB for the local warehouse, Snowflake as the cloud target

**Status:** accepted

## Context
The project must run end to end on a laptop without cloud credentials (`make demo`), but the target
platform is Snowflake.

## Decision
One dbt project with two targets. `dev` uses dbt-duckdb on a local file and `snowflake` uses
key-pair authentication. Schema names are the same in both. Date arithmetic goes through
adapter-dispatched macros. `fact_general_ledger` uses `delete+insert` on DuckDB and `merge` on Snowflake.

## Consequences
* The full pipeline and its 202 dbt tests run locally and in CI with no cloud cost.
* Snowflake compatibility is checked by `dbt compile --target snowflake` in CI only when secrets exist.
  The job reports itself as skipped otherwise, and a skip is never counted as a pass. It has not been run
  against a real account yet.
* Snowflake-only features (masking, row access policies, resource monitors) are plain SQL in
  `warehouse/snowflake/` and are not exercised locally.
