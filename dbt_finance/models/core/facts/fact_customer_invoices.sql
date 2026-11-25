-- Grain: one customer invoice. Customer attributes are joined point-in-time (SCD2 version valid
-- when the invoice was created). Settlement measures reflect all events up to the data horizon.
with invoices as (
    select * from {{ ref('stg_erp__customer_invoices') }} where not is_deleted
),

accounts as (
    select * from {{ ref('stg_erp__customer_accounts') }}
),

events as (
    select
        invoice_id,
        sum(case when event_type = 'ISSUE' then amount_functional end) as invoice_amount_functional,
        sum(case when event_type = 'RECEIPT' then -amount_transaction else 0 end) as paid_amount,
        sum(case when event_type in ('CREDIT_NOTE', 'WRITE_OFF') then -amount_transaction else 0 end)
            as credited_amount,
        sum(case when event_type = 'WRITE_OFF' then -amount_transaction else 0 end) as written_off_amount,
        sum(amount_transaction) as outstanding_amount,
        sum(amount_functional) as outstanding_amount_functional,
        max(case when event_type = 'RECEIPT' then event_date end) as last_payment_date,
        count(case when event_type = 'RECEIPT' then 1 end) as payment_count
    from {{ ref('int_customer_invoice_events') }}
    group by 1
),

customers as (
    select * from {{ ref('dim_customer') }}
),

rates as (
    select * from {{ ref('int_fx_rates_monthly') }}
),

entities as (
    select entity_id, functional_currency from {{ ref('dim_legal_entity') }}
)

select
    i.invoice_id,
    i.invoice_number,
    i.entity_id,
    {{ surrogate_key(['i.entity_id']) }} as entity_key,
    coalesce(c.customer_key, {{ surrogate_key(["'-1'"]) }}) as customer_key,
    a.crm_customer_id as customer_id,
    i.erp_customer_id,
    c.segment as customer_segment_at_invoice,
    c.country as customer_country,
    i.sales_order_id,
    i.invoice_date,
    i.due_date,
    {{ fiscal_period('i.invoice_date') }} as fiscal_period,
    i.currency,
    i.subtotal,
    i.tax_amount,
    i.invoice_amount,
    e.invoice_amount_functional,
    en.functional_currency,
    {{ to_reporting('e.invoice_amount_functional', 'r.avg_rate_to_reporting') }} as invoice_amount_reporting,
    e.paid_amount,
    e.credited_amount,
    e.written_off_amount,
    e.outstanding_amount,
    e.outstanding_amount_functional,
    e.payment_count,
    e.last_payment_date,
    case when e.outstanding_amount = 0 and e.last_payment_date is not null
        then {{ days_between('i.invoice_date', 'e.last_payment_date') }} end as days_to_pay,
    case when e.outstanding_amount = 0 and e.last_payment_date is not null
        then {{ days_between('i.due_date', 'e.last_payment_date') }} end as days_paid_after_due,
    i.invoice_status as source_invoice_status,
    i.outstanding_amount as source_outstanding_amount,
    i.outstanding_amount <> e.outstanding_amount as is_status_out_of_sync,
    i.is_intercompany,
    i.counterparty_entity_id,
    i.journal_id,
    'ERP' as source_system,
    i.ingestion_batch_id,
    {{ audit_columns() }}
from invoices as i
left join accounts as a on i.erp_customer_id = a.erp_customer_id
left join events as e on i.invoice_id = e.invoice_id
left join entities as en on i.entity_id = en.entity_id
left join rates as r on {{ fiscal_period('i.invoice_date') }} = r.fiscal_period and en.functional_currency = r.currency
left join customers as c
    on
        a.crm_customer_id = c.customer_id
        and i.created_at >= c.valid_from and i.created_at < c.valid_to
