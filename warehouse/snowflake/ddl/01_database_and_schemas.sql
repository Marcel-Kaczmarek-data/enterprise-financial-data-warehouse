-- =====================================================================================
-- Database and layer schemas (same names as the local DuckDB warehouse).
-- STATUS: NOT executed against a real Snowflake account.
-- =====================================================================================
use role sysadmin;

create database if not exists finance_dw
    data_retention_time_in_days = 7      -- Time Travel window for production data
    comment = 'Enterprise financial data warehouse';

create schema if not exists finance_dw.finance_raw          data_retention_time_in_days = 1;
create schema if not exists finance_dw.finance_staging;
create schema if not exists finance_dw.finance_intermediate  data_retention_time_in_days = 1;
create schema if not exists finance_dw.finance_core          data_retention_time_in_days = 30;
create schema if not exists finance_dw.finance_marts         data_retention_time_in_days = 30;
create schema if not exists finance_dw.finance_audit         data_retention_time_in_days = 90;
create schema if not exists finance_dw.finance_monitoring;
create schema if not exists finance_dw.finance_snapshots     data_retention_time_in_days = 30;
create schema if not exists finance_dw.governance;           -- masking / row access policies

-- Development environment as a zero-copy clone (metadata-only; storage is shared until changed).
-- create database finance_dw_dev clone finance_dw;

-- Time Travel examples for audit / incident recovery:
--   select * from finance_dw.finance_core.fact_general_ledger at(offset => -3600);
--   create table finance_dw.finance_core.fact_general_ledger_restore
--       clone finance_dw.finance_core.fact_general_ledger before(statement => '<query_id>');
--   undrop table finance_dw.finance_marts.mart_balance_sheet;
