-- Receivables aging by reporting date, entity and bucket, with DSO.
-- Grain: snapshot_date x entity_id x aging_bucket (external customers; intercompany excluded).
-- DSO = closing receivables (EUR) / external revenue of the trailing 3 months (EUR) x 91 days,
-- computed from aggregated numerator and denominator (never an average of ratios).
with aging as (
    select
        snapshot_date,
        fiscal_period,
        entity_id,
        aging_bucket,
        aging_bucket_order,
        count(*) as open_invoices,
        sum(outstanding_amount_reporting) as outstanding_reporting,
        sum(case when is_overdue then outstanding_amount_reporting else 0 end) as overdue_reporting
    from {{ ref('fact_receivables_snapshot') }}
    where not is_intercompany
    group by 1, 2, 3, 4, 5
),

revenue as (
    select entity_id, fiscal_period, sum(amount_reporting) as revenue_reporting
    from {{ ref('mart_profit_and_loss') }}
    where reporting_scope = 'STANDALONE' and statement_line in ('Product revenue', 'Service revenue')
    group by 1, 2
),

revenue_3m as (
    select
        entity_id,
        fiscal_period,
        sum(revenue_reporting) over (partition by entity_id order by fiscal_period rows between 2 preceding and current row)
            as revenue_trailing_3m
    from revenue
),

totals as (
    select snapshot_date, fiscal_period, entity_id, sum(outstanding_reporting) as total_outstanding_reporting
    from aging
    group by 1, 2, 3
)

select
    a.snapshot_date,
    a.fiscal_period,
    a.entity_id,
    e.entity_name,
    e.country_name,
    a.aging_bucket,
    a.aging_bucket_order,
    a.open_invoices,
    a.outstanding_reporting,
    a.overdue_reporting,
    t.total_outstanding_reporting,
    {{ safe_divide('a.outstanding_reporting', 't.total_outstanding_reporting') }} as share_of_receivables,
    r.revenue_trailing_3m,
    {{ safe_divide('t.total_outstanding_reporting * 91', 'r.revenue_trailing_3m') }} as days_sales_outstanding,
    '{{ var("group_reporting_currency") }}' as reporting_currency,
    {{ audit_columns() }}
from aging as a
inner join totals as t
    on a.snapshot_date = t.snapshot_date and a.entity_id = t.entity_id
left join revenue_3m as r on a.entity_id = r.entity_id and a.fiscal_period = r.fiscal_period
left join {{ ref('dim_legal_entity') }} as e on a.entity_id = e.entity_id
