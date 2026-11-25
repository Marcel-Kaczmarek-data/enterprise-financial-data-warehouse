-- Grain: one open (posted) supplier invoice at a reporting date (month-ends + latest data date).
-- Same as-of logic as receivables: payments dated after the reporting date do not change it.
with events as (
    select * from {{ ref('int_vendor_invoice_events') }}
),

invoices as (
    select * from {{ ref('fact_vendor_invoices') }} where not is_blocked
),

horizon as (
    select max(posting_date) as max_date from {{ ref('fact_general_ledger') }}
),

snapshot_dates as (
    select period_end as snapshot_date
    from {{ ref('dim_fiscal_period') }}
    where period_end <= (select max_date from horizon)
    union
    select max_date from horizon
),

positions as (
    select
        d.snapshot_date,
        ev.vendor_invoice_id,
        sum(ev.amount_transaction) as outstanding_amount,
        sum(ev.amount_functional) as outstanding_amount_functional
    from snapshot_dates as d
    inner join events as ev on ev.event_date <= d.snapshot_date
    group by 1, 2
    having sum(ev.amount_transaction) <> 0
),

rates as (
    select * from {{ ref('int_fx_rates_monthly') }}
),

buckets as (
    select * from {{ ref('aging_buckets') }}
)

select
    p.snapshot_date,
    {{ fiscal_period('p.snapshot_date') }} as fiscal_period,
    i.vendor_invoice_id,
    i.vendor_invoice_number,
    i.entity_id,
    i.entity_key,
    i.vendor_key,
    i.vendor_id,
    i.vendor_name,
    i.vendor_category,
    i.is_intercompany,
    i.invoice_date,
    i.due_date,
    i.currency,
    i.invoice_amount,
    p.outstanding_amount,
    p.outstanding_amount_functional,
    i.functional_currency,
    {{ to_reporting('p.outstanding_amount_functional', 'r.closing_rate_to_reporting') }} as outstanding_amount_reporting,
    {{ days_between('i.due_date', 'p.snapshot_date') }} as days_overdue,
    b.bucket_name as aging_bucket,
    b.bucket_order as aging_bucket_order,
    {{ days_between('i.due_date', 'p.snapshot_date') }} > 0 as is_overdue,
    {{ audit_columns() }}
from positions as p
inner join invoices as i on p.vendor_invoice_id = i.vendor_invoice_id
left join rates as r on {{ fiscal_period('p.snapshot_date') }} = r.fiscal_period and i.functional_currency = r.currency
left join buckets as b
    on
        {{ days_between('i.due_date', 'p.snapshot_date') }} >= coalesce(b.min_days_overdue, -100000)
        and {{ days_between('i.due_date', 'p.snapshot_date') }} <= coalesce(b.max_days_overdue, 100000)
