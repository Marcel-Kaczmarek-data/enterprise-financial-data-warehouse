{{ config(
    materialized='incremental',
    unique_key='journal_line_id',
    incremental_strategy=('merge' if target.type == 'snowflake' else 'delete+insert'),
    on_schema_change='append_new_columns',
    cluster_by=(['fiscal_period', 'entity_id'] if target.type == 'snowflake' else none)
) }}
-- Grain: one POSTED journal line. Additive measures: debit/credit/signed amounts.
-- Incremental: re-reads lines whose journal or line changed within the lookback window, so
-- late-arriving and back-dated postings (posting_date in a past period, created later) are
-- merged idempotently on journal_line_id. Posted lines are never updated in the source; a
-- correction arrives as a REVERSAL journal, preserving the audit trail.
with gl as (
    select * from {{ ref('int_general_ledger_enriched') }}
    {% if is_incremental() %}
        where source_updated_at > (
            select {{ add_days('cast(max(source_updated_at) as date)', -var('gl_incremental_lookback_days')) }}
            from {{ this }}
        )
    {% endif %}
)

select
    gl.journal_line_id,
    gl.journal_id,
    gl.line_number,
    {{ surrogate_key(['gl.entity_id']) }} as entity_key,
    {{ surrogate_key(['gl.group_account_code']) }} as account_key,
    {{ surrogate_key(['gl.cost_center_id']) }} as cost_center_key,
    {{ surrogate_key(["coalesce(gl.profit_center_id, '-1')"]) }} as profit_center_key,
    extract(year from gl.posting_date) * 10000 + extract(month from gl.posting_date) * 100
        + extract(day from gl.posting_date) as posting_date_key,
    gl.entity_id,
    gl.fiscal_period,
    gl.fiscal_year,
    gl.posting_date,
    gl.transaction_date,
    gl.journal_type,
    gl.account_id,
    gl.local_account_code,
    gl.group_account_code,
    gl.statement,
    gl.statement_line,
    gl.cost_center_id,
    gl.department_id,
    gl.profit_center_id,
    gl.counterparty_entity_id,
    gl.debit_amount,
    gl.credit_amount,
    gl.signed_amount_functional,
    gl.functional_currency,
    gl.transaction_amount,
    gl.transaction_currency,
    gl.transaction_to_functional_rate,
    gl.signed_amount_reporting,
    gl.reporting_currency,
    gl.functional_to_reporting_rate,
    gl.reporting_rate_type,
    -- lineage back to the source system record
    gl.source_system,
    gl.source_document_type,
    gl.source_document_id,
    gl.reference_number,
    gl.journal_description,
    gl.line_description,
    gl.reversal_of_journal_id,
    gl.created_by,
    gl.journal_created_at,
    gl.mapping_version as account_mapping_version,
    gl.ingestion_batch_id,
    gl.source_updated_at,
    {{ audit_columns() }}
from gl
