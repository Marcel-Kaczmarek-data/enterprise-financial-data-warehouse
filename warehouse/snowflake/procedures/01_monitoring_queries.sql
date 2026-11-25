-- =====================================================================================
-- Snowflake cost and performance monitoring (ACCOUNT_USAGE has up to ~45 min latency).
-- STATUS: NOT executed - Snowflake monitoring is not claimed operational without an account.
-- =====================================================================================

-- Credit consumption per warehouse and day
select warehouse_name, date_trunc('day', start_time) as day, sum(credits_used) as credits
from snowflake.account_usage.warehouse_metering_history
where start_time >= dateadd(day, -30, current_timestamp())
group by 1, 2 order by 2, 1;

-- Most expensive queries (elapsed time and bytes scanned), dbt models identified by query tag
select query_id, query_tag, warehouse_name, total_elapsed_time / 1000 as seconds,
       bytes_scanned / power(1024, 3) as gb_scanned, partitions_scanned, partitions_total,
       round(partitions_scanned / nullif(partitions_total, 0), 3) as pruning_ratio
from snowflake.account_usage.query_history
where start_time >= dateadd(day, -7, current_timestamp()) and warehouse_name like 'FINANCE_%'
order by total_elapsed_time desc limit 50;

-- Failed queries
select start_time, user_name, query_tag, error_code, error_message
from snowflake.account_usage.query_history
where execution_status = 'FAIL' and start_time >= dateadd(day, -1, current_timestamp());

-- Storage by schema (active, time travel, failsafe)
select table_schema, sum(active_bytes) / power(1024, 3) as active_gb,
       sum(time_travel_bytes) / power(1024, 3) as time_travel_gb, sum(failsafe_bytes) / power(1024, 3) as failsafe_gb
from snowflake.account_usage.table_storage_metrics
where table_catalog = 'FINANCE_DW' and deleted = false group by 1;

-- Clustering health of the GL fact (only add clustering if pruning_ratio stays poor at scale)
select system$clustering_information('finance_dw.finance_core.fact_general_ledger', '(fiscal_period, entity_id)');
