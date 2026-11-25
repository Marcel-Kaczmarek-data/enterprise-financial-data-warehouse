-- Grain: one supplier invoice (including blocked duplicates, flagged and carrying zero liability).
with invoices as (
    select * from {{ ref('stg_erp__vendor_invoices') }}
),

events as (
    select
        vendor_invoice_id,
        sum(case when event_type = 'ISSUE' then amount_functional end) as invoice_amount_functional,
        sum(case when event_type = 'PAYMENT' then -amount_transaction else 0 end) as settled_amount,
        sum(amount_transaction) as outstanding_amount,
        sum(amount_functional) as outstanding_amount_functional,
        max(case when event_type = 'PAYMENT' then event_date end) as payment_date
    from {{ ref('int_vendor_invoice_events') }}
    group by 1
),

discounts as (
    select document_id as vendor_invoice_id, sum(discount_amount) as discount_taken
    from {{ ref('stg_erp__payment_allocations') }}
    where document_type = 'VENDOR_INVOICE'
    group by 1
),

vendors as (
    select * from {{ ref('dim_vendor') }}
),

entities as (
    select entity_id, functional_currency from {{ ref('dim_legal_entity') }}
),

rates as (
    select * from {{ ref('int_fx_rates_monthly') }}
)

select
    i.vendor_invoice_id,
    i.vendor_invoice_number,
    i.entity_id,
    {{ surrogate_key(['i.entity_id']) }} as entity_key,
    v.vendor_key,
    i.vendor_id,
    v.vendor_name,
    coalesce(v.vendor_category, i.expense_category) as vendor_category,
    i.purchase_order_id,
    i.expense_category,
    i.invoice_date,
    i.received_date,
    i.due_date,
    {{ fiscal_period('i.invoice_date') }} as fiscal_period,
    i.currency,
    i.subtotal,
    i.tax_amount,
    i.invoice_amount,
    i.approved_amount,
    coalesce(e.invoice_amount_functional, 0) as invoice_amount_functional,
    en.functional_currency,
    {{ to_reporting('coalesce(e.invoice_amount_functional, 0)', 'r.avg_rate_to_reporting') }} as invoice_amount_reporting,
    coalesce(e.settled_amount, 0) as settled_amount,
    coalesce(d.discount_taken, 0) as discount_taken,
    coalesce(e.outstanding_amount, 0) as outstanding_amount,
    coalesce(e.outstanding_amount_functional, 0) as outstanding_amount_functional,
    e.payment_date,
    case when e.payment_date is not null then {{ days_between('i.invoice_date', 'e.payment_date') }} end as days_to_pay,
    case when e.payment_date is not null then {{ days_between('i.due_date', 'e.payment_date') }} end as days_paid_after_due,
    i.payment_status as source_payment_status,
    i.approval_status,
    i.journal_id is null as is_blocked,
    i.is_intercompany,
    i.counterparty_entity_id,
    i.journal_id,
    i.ingestion_batch_id,
    {{ audit_columns() }}
from invoices as i
left join events as e on i.vendor_invoice_id = e.vendor_invoice_id
left join discounts as d on i.vendor_invoice_id = d.vendor_invoice_id
left join entities as en on i.entity_id = en.entity_id
left join rates as r on {{ fiscal_period('i.invoice_date') }} = r.fiscal_period and en.functional_currency = r.currency
left join vendors as v
    on i.vendor_id = v.vendor_id and v.is_current
