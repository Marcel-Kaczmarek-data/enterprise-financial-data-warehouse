-- Payables aging by reporting date, entity and bucket, with DPO.
-- Grain: snapshot_date x entity_id x aging_bucket (external suppliers; intercompany excluded).
-- DPO = closing payables (EUR) / supplier invoice intake of the trailing 3 months (EUR) x 91.
-- Purchases rather than COGS are used as denominator because most supplier spend is operating
-- expense in this business (documented in docs/financial-kpis.md).
with aging as (
    select
        snapshot_date,
        fiscal_period,
        entity_id,
        aging_bucket,
        aging_bucket_order,
        count(*) as open_invoices,
        sum(outstanding_amount_reporting) as outstanding_reporting,
        sum(case when is_overdue then outstanding_amount_reporting else 0 end) as overdue_reporting,
        sum(case when not is_overdue and days_overdue >= -14 then outstanding_amount_reporting else 0 end)
            as due_next_14_days_reporting
    from {{ ref('fact_payables_snapshot') }}
    where not is_intercompany
    group by 1, 2, 3, 4, 5
),

purchases as (
    select entity_id, fiscal_period, sum(invoice_amount_reporting) as purchases_reporting
    from {{ ref('fact_vendor_invoices') }}
    where not is_blocked and not is_intercompany
    group by 1, 2
),

purchases_3m as (
    select
        entity_id,
        fiscal_period,
        sum(purchases_reporting) over (partition by entity_id order by fiscal_period rows between 2 preceding and current row)
            as purchases_trailing_3m
    from purchases
),

totals as (
    select snapshot_date, entity_id, sum(outstanding_reporting) as total_outstanding_reporting
    from aging
    group by 1, 2
)

select
    a.*,
    e.entity_name,
    t.total_outstanding_reporting,
    p.purchases_trailing_3m,
    {{ safe_divide('t.total_outstanding_reporting * 91', 'p.purchases_trailing_3m') }} as days_payable_outstanding,
    '{{ var("group_reporting_currency") }}' as reporting_currency,
    {{ audit_columns() }}
from aging as a
inner join totals as t on a.snapshot_date = t.snapshot_date and a.entity_id = t.entity_id
left join purchases_3m as p on a.entity_id = p.entity_id and a.fiscal_period = p.fiscal_period
left join {{ ref('dim_legal_entity') }} as e on a.entity_id = e.entity_id
