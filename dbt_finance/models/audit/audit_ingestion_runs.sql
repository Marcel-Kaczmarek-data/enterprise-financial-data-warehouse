-- Ingestion runs with source-to-target record count reconciliation.
-- Grain: one extraction batch.
select
    b.batch_id,
    b.source_system,
    b.source_table,
    b.extraction_mode,
    b.status,
    cast(b.started_at as timestamp with time zone) as started_at,
    cast(b.finished_at as timestamp with time zone) as finished_at,
    date_diff('millisecond', cast(b.started_at as timestamp with time zone),
              cast(b.finished_at as timestamp with time zone)) / 1000.0 as duration_seconds,
    b.watermark_from,
    b.watermark_to,
    b.rows_source,
    b.rows_extracted,
    b.rows_quarantined,
    case
        when b.status <> 'SUCCEEDED' then 'FAILED'
        when b.rows_source is null then 'NOT_APPLICABLE'
        when b.rows_source = b.rows_extracted + coalesce(b.rows_quarantined, 0) then 'RECONCILED'
        else 'COUNT_MISMATCH'
    end as record_count_status,
    l.status as raw_load_status,
    l.rows_loaded as rows_loaded_to_raw,
    l.loaded_at as raw_loaded_at,
    b.error
from {{ source('pipeline_audit', 'ingestion_batches') }} as b
left join {{ source('pipeline_audit', 'raw_load_history') }} as l on b.batch_id = l.batch_id
