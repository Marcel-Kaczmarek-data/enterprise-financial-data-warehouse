-- Data freshness per raw source table: latest successful load and latest business timestamp.
-- Grain: source system x source table.
with loads as (
    select
        source_system,
        source_table,
        max(loaded_at) as last_loaded_at,
        sum(rows_loaded) as total_rows_loaded,
        count(*) as manifests_loaded
    from {{ source('pipeline_audit', 'raw_load_history') }}
    where status = 'LOADED'
    group by 1, 2
),

gl_activity as (
    select max(posting_date) as latest_posting_date from {{ ref('fact_general_ledger') }}
)

select
    l.*,
    g.latest_posting_date,
    date_diff('hour', l.last_loaded_at, current_timestamp) as hours_since_last_load
from loads as l
cross join gl_activity as g
