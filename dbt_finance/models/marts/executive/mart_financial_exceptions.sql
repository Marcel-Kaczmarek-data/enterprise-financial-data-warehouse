-- Unified financial exception register (the review queue for finance operations).
-- Grain: one exception. Severity: CRITICAL blocks report publication (see publication gate),
-- WARNING requires review, INFO is informational. Ambiguous bank matches are never auto-approved.
with subledger as (
    select
        {{ surrogate_key(["'SUBLEDGER'", 'ledger', 'entity_id', 'fiscal_period']) }} as exception_id,
        'RECONCILIATION' as exception_domain,
        ledger || '_VS_GL' as exception_type,
        case when abs(difference) >= 1 then 'CRITICAL' else 'WARNING' end as severity,
        entity_id,
        fiscal_period,
        difference as discrepancy_amount,
        functional_currency as currency,
        ledger as affected_object,
        cast(null as varchar) as affected_ids,
        'Subledger open items differ from the GL control account balance by '
            || cast(round(difference, 2) as varchar) || ' ' || functional_currency as explanation
    from {{ ref('int_subledger_reconciliation') }}
    where reconciliation_status = 'DIFFERENCE'
),

bank as (
    select
        {{ surrogate_key(["'BANK'", 'reconciliation_item_id']) }},
        'BANK_RECONCILIATION',
        match_status,
        severity,
        entity_id,
        fiscal_period,
        amount,
        cast(null as varchar),
        bank_account_id,
        coalesce(cast(journal_id as varchar), '') || '|' || coalesce(bank_transaction_id, ''),
        case match_status
            when 'UNMATCHED_LEDGER' then 'Ledger cash entry without a bank statement line'
            when 'UNMATCHED_BANK' then 'Bank statement line without a ledger entry'
            when 'POSSIBLE_DUPLICATE' then 'Bank line identical to another line on the same day (possible duplicate debit)'
            when 'AMBIGUOUS_REVIEW' then 'Several equally valid candidates - manual review required'
        end
    from {{ ref('int_bank_transaction_matching') }}
    where match_status in ('UNMATCHED_LEDGER', 'UNMATCHED_BANK', 'POSSIBLE_DUPLICATE', 'AMBIGUOUS_REVIEW')
),

three_way as (
    select
        {{ surrogate_key(["'3WAY'", 'match_id']) }},
        'PROCURE_TO_PAY',
        match_status,
        severity,
        entity_id,
        {{ fiscal_period('invoice_date') }},
        discrepancy_amount,
        currency,
        'VENDOR_INVOICE',
        cast(vendor_invoice_id as varchar),
        explanation
    from {{ ref('int_three_way_matching') }}
    where match_status <> 'MATCHED'
),

intercompany as (
    select
        {{ surrogate_key(["'IC'", 'elimination_id']) }},
        'INTERCOMPANY',
        elimination_type || '_' || reconciliation_status,
        case when reconciliation_status = 'MISSING_COUNTERPART' then 'WARNING' else 'WARNING' end,
        side_a_entity,
        fiscal_period,
        elimination_difference,
        '{{ var("group_reporting_currency") }}',
        side_a_entity || '->' || side_b_entity,
        elimination_id,
        'Intercompany positions differ by ' || cast(round(elimination_difference, 2) as varchar)
            || ' EUR (' || cast(round(difference_pct, 2) as varchar) || '%)'
    from {{ ref('mart_intercompany_reconciliation') }}
    where reconciliation_status <> 'MATCHED'
),

fx as (
    select
        {{ surrogate_key(["'FX'", 'rate_date', 'target_currency', 'rate_type', 'publication_timestamp']) }},
        'MARKET_DATA',
        quarantine_reason,
        'INFO',
        cast(null as varchar),
        {{ fiscal_period('rate_date') }},
        exchange_rate,
        target_currency,
        'EXCHANGE_RATE',
        cast(rate_date as varchar) || ' ' || source_currency || '/' || target_currency,
        'Rate publication excluded from conversion'
    from {{ ref('int_fx_rate_quarantine') }}
),

invoice_status as (
    select
        {{ surrogate_key(["'ARSTATUS'", 'invoice_id']) }},
        'SOURCE_DATA',
        'INVOICE_STATUS_OUT_OF_SYNC',
        'WARNING',
        entity_id,
        fiscal_period,
        source_outstanding_amount - outstanding_amount,
        currency,
        'CUSTOMER_INVOICE',
        cast(invoice_id as varchar),
        'ERP outstanding amount disagrees with settlement events (source status maintenance issue)'
    from {{ ref('fact_customer_invoices') }}
    where is_status_out_of_sync
)

select *, current_timestamp as detected_at from subledger
union all select *, current_timestamp from bank
union all select *, current_timestamp from three_way
union all select *, current_timestamp from intercompany
union all select *, current_timestamp from fx
union all select *, current_timestamp from invoice_status
