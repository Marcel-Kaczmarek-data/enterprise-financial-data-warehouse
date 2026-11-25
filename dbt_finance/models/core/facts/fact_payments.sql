-- Grain: one ERP payment or receipt. payment_amount is gross; bank_charge_amount was deducted by
-- the bank on receipt, so the cash movement equals payment_amount - bank_charge_amount.
select
    p.payment_id,
    p.payment_number,
    p.entity_id,
    {{ surrogate_key(['p.entity_id']) }} as entity_key,
    {{ surrogate_key(['p.bank_account_id']) }} as bank_account_key,
    p.payment_date,
    {{ fiscal_period('p.payment_date') }} as fiscal_period,
    p.payment_direction,
    p.payment_type,
    p.payment_method,
    p.currency,
    p.payment_amount,
    p.bank_charge_amount,
    case when p.payment_direction = 'INBOUND' then p.payment_amount - p.bank_charge_amount
         else -(p.payment_amount + p.bank_charge_amount) end as cash_movement,
    p.functional_amount,
    p.payment_status,
    p.bank_account_id,
    p.bank_reference,
    p.counterparty_type,
    p.counterparty_id,
    p.journal_id,
    p.ingestion_batch_id,
    {{ audit_columns() }}
from {{ ref('stg_erp__payments') }} as p
