{{ config(
    materialized='incremental',
    unique_key=['snapshot_date', 'invoice_id'],
    incremental_strategy=('merge' if target.type == 'snowflake' else 'delete+insert')
) }}
-- Grain: one open customer invoice at a reporting date (month-ends + latest data date).
-- Historical as-of logic: outstanding = sum of settlement events dated <= snapshot_date, so an
-- invoice paid after the reporting date is still open in that reporting date's aging.
-- Incremental: the last two snapshot dates are rebuilt each run (late allocations / back-dated
-- credit notes); earlier closed-period snapshots are immutable once published.
with events as (
    select * from {{ ref('int_customer_invoice_events') }}
),

invoices as (
    select * from {{ ref('fact_customer_invoices') }}
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

{% if is_incremental() %}
target_dates as (
    select snapshot_date from snapshot_dates
    where snapshot_date >= (
        select coalesce(max(snapshot_date), cast('1900-01-01' as date)) from {{ this }}
        where snapshot_date < (select max(snapshot_date) from {{ this }})
    )
),
{% else %}
target_dates as (select snapshot_date from snapshot_dates),
{% endif %}

positions as (
    select
        d.snapshot_date,
        ev.invoice_id,
        sum(ev.amount_transaction) as outstanding_amount,
        sum(ev.amount_functional) as outstanding_amount_functional
    from target_dates as d
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
    i.invoice_id,
    i.invoice_number,
    i.entity_id,
    i.entity_key,
    i.customer_key,
    i.customer_id,
    i.customer_segment_at_invoice,
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
inner join invoices as i on p.invoice_id = i.invoice_id
left join rates as r on {{ fiscal_period('p.snapshot_date') }} = r.fiscal_period and i.functional_currency = r.currency
left join buckets as b
    on
        {{ days_between('i.due_date', 'p.snapshot_date') }} >= coalesce(b.min_days_overdue, -100000)
        and {{ days_between('i.due_date', 'p.snapshot_date') }} <= coalesce(b.max_days_overdue, 100000)
