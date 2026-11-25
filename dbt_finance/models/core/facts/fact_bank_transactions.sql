-- Grain: one bank statement line (deduplicated on bank_transaction_id; re-delivered feed rows
-- collapse in staging). Amounts are signed in account currency: + inflow, - outflow.
select
    t.bank_transaction_id,
    t.bank_account_id,
    {{ surrogate_key(['t.bank_account_id']) }} as bank_account_key,
    b.entity_id,
    t.transaction_date,
    t.value_date,
    {{ fiscal_period('t.value_date') }} as fiscal_period,
    t.transaction_type,
    t.currency,
    t.amount,
    t.bank_reference,
    t.description,
    t.counterparty_name,
    t.reconciliation_status as bank_booking_status,
    t.statement_id,
    t.source_file,
    t.ingestion_batch_id,
    {{ audit_columns() }}
from {{ ref('stg_bank__transactions') }} as t
left join {{ ref('stg_erp__bank_accounts') }} as b on t.bank_account_id = b.bank_account_id
