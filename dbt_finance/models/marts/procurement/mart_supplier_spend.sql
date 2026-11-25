-- Supplier spend, concentration and payment performance (posted external supplier invoices, EUR).
-- Grain: entity x fiscal_period x vendor.
with spend as (
    select
        entity_id,
        fiscal_period,
        vendor_id,
        vendor_name,
        vendor_category,
        count(*) as invoices,
        sum(invoice_amount_reporting) as spend_reporting,
        sum(discount_taken) as discounts_taken_transaction,
        avg(days_to_pay) as avg_days_to_pay,
        sum(case when days_paid_after_due > 0 then 1 else 0 end) as invoices_paid_late
    from {{ ref('fact_vendor_invoices') }}
    where not is_blocked and not is_intercompany
    group by 1, 2, 3, 4, 5
)

select
    s.*,
    sum(s.spend_reporting) over (partition by s.entity_id, s.fiscal_period) as entity_period_spend,
    {{ safe_divide('s.spend_reporting', 'sum(s.spend_reporting) over (partition by s.entity_id, s.fiscal_period)') }}
        as spend_share,
    rank() over (partition by s.entity_id, s.fiscal_period order by s.spend_reporting desc) as spend_rank,
    '{{ var("group_reporting_currency") }}' as reporting_currency,
    {{ audit_columns() }}
from spend as s
