-- =====================================================================================
-- Virtual warehouses and resource monitors (Snowflake). Run as SYSADMIN / ACCOUNTADMIN.
-- STATUS: written against Snowflake documentation; NOT executed against a real account.
-- Sizes are deliberately XSMALL; scale only with benchmark evidence (docs/cost-analysis.md).
-- =====================================================================================
use role accountadmin;

create resource monitor if not exists finance_monthly_monitor
    with credit_quota = 100 frequency = monthly start_timestamp = immediately
    triggers on 75 percent do notify
             on 90 percent do suspend
             on 100 percent do suspend_immediate;

use role sysadmin;

-- Separate compute per workload: ingestion and ELT never compete with BI queries.
create warehouse if not exists finance_ingest_wh
    warehouse_size = xsmall auto_suspend = 60 auto_resume = true initially_suspended = true
    comment = 'COPY INTO loads from the S3 external stage';
create warehouse if not exists finance_transform_wh
    warehouse_size = xsmall auto_suspend = 60 auto_resume = true initially_suspended = true
    comment = 'dbt transformations';
create warehouse if not exists finance_bi_wh
    warehouse_size = xsmall auto_suspend = 300 auto_resume = true initially_suspended = true
    min_cluster_count = 1 max_cluster_count = 2 scaling_policy = economy
    comment = 'Power BI / dashboard queries (multi-cluster only for concurrency, Enterprise edition)';
create warehouse if not exists finance_dev_wh
    warehouse_size = xsmall auto_suspend = 60 auto_resume = true initially_suspended = true;
create warehouse if not exists finance_admin_wh
    warehouse_size = xsmall auto_suspend = 60 auto_resume = true initially_suspended = true;

alter warehouse finance_ingest_wh set resource_monitor = finance_monthly_monitor;
alter warehouse finance_transform_wh set resource_monitor = finance_monthly_monitor;
alter warehouse finance_bi_wh set resource_monitor = finance_monthly_monitor;
alter warehouse finance_dev_wh set resource_monitor = finance_monthly_monitor;

-- Query tagging: dbt sets query_tag (profiles.yml); ingestion sessions set their own tag.
alter warehouse finance_ingest_wh set statement_timeout_in_seconds = 3600;
alter warehouse finance_bi_wh set statement_timeout_in_seconds = 600;
