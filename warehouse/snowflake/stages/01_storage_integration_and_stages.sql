-- =====================================================================================
-- S3 storage integration, file formats, external stage and COPY INTO with load history.
-- STATUS: NOT executed against a real Snowflake account. Terraform (infrastructure/terraform)
-- creates the IAM role trusted by the integration.
-- =====================================================================================
use role accountadmin;
create storage integration if not exists finance_s3_integration
    type = external_stage
    storage_provider = 's3'
    enabled = true
    storage_aws_role_arn = 'arn:aws:iam::<account_id>:role/fdw-snowflake-s3-read'
    storage_allowed_locations = ('s3://<landing-bucket>/landing/', 's3://<landing-bucket>/manifests/');
-- desc integration finance_s3_integration;  -> copy STORAGE_AWS_IAM_USER_ARN / EXTERNAL_ID into Terraform
grant usage on integration finance_s3_integration to role data_engineer;

use role data_engineer;
use schema finance_dw.finance_raw;

create file format if not exists ff_parquet type = parquet use_logical_type = true;
create file format if not exists ff_json type = json strip_outer_array = false;

create stage if not exists stg_landing
    storage_integration = finance_s3_integration
    url = 's3://<landing-bucket>/landing/'
    file_format = ff_parquet;

-- Raw tables mirror the contracts plus ingestion metadata. Example for journal lines:
create table if not exists erp__journal_lines (
    journal_line_id number, journal_id number, line_number number, account_id number,
    debit_amount number(19, 4), credit_amount number(19, 4), transaction_currency varchar,
    transaction_amount number(19, 4), functional_currency varchar, functional_currency_amount number(19, 4),
    exchange_rate number(24, 10), cost_center_id varchar, profit_center_id varchar, department_id varchar,
    counterparty_entity_id varchar, line_description varchar, created_at timestamp_tz, updated_at timestamp_tz,
    _batch_id varchar, _source_system varchar, _source_table varchar, _source_file varchar,
    _extracted_at timestamp_tz, _manifest_key varchar, _loaded_at timestamp_tz default current_timestamp());

-- Incremental, idempotent load: Snowflake load metadata skips files already loaded (64 days);
-- MATCH_BY_COLUMN_NAME tolerates additive schema drift; ON_ERROR keeps bad files out.
copy into erp__journal_lines
    from @stg_landing/erp/journal_lines/
    file_format = (format_name = ff_parquet)
    match_by_column_name = case_insensitive
    include_metadata = (_source_file = metadata$filename)
    on_error = abort_statement;

-- Load history / audit
-- select * from table(information_schema.copy_history(
--     table_name => 'ERP__JOURNAL_LINES', start_time => dateadd(day, -7, current_timestamp())));

-- Optional alternative pattern (not in the core workflow): Snowpipe auto-ingest + Streams/Tasks.
-- Airflow + dbt remain the single orchestration path; see docs/adr/ADR-006 for the trade-off.
-- create pipe pipe_journal_lines auto_ingest = true as copy into erp__journal_lines from @stg_landing/erp/journal_lines/
--     file_format = (format_name = ff_parquet) match_by_column_name = case_insensitive;
-- create stream journal_lines_stream on table erp__journal_lines append_only = true;
