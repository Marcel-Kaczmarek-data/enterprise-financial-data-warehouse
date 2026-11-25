-- Revenue mix for the trailing twelve months: region x customer segment, with share of total and
-- growth against the twelve months before.
with bounds as (
    select
        max(fiscal_period) as last_period,
        strftime(cast(max(fiscal_period) || '-01' as date) - interval 12 month, '%Y-%m') as ttm_start,
        strftime(cast(max(fiscal_period) || '-01' as date) - interval 24 month, '%Y-%m') as prior_start
    from finance_marts.mart_revenue_analysis
),

revenue as (
    select
        r.region,
        r.customer_segment,
        sum(case when r.fiscal_period > b.ttm_start then r.revenue_reporting else 0 end) as ttm_eur,
        sum(
            case
                when r.fiscal_period > b.prior_start and r.fiscal_period <= b.ttm_start
                    then r.revenue_reporting
                else 0
            end
        ) as prior_ttm_eur
    from finance_marts.mart_revenue_analysis as r
    cross join bounds as b
    group by r.region, r.customer_segment
)

select
    region,
    customer_segment,
    round(ttm_eur, 0) as ttm_revenue_eur,
    round(ttm_eur / sum(ttm_eur) over () * 100, 1) as share_pct,
    round((ttm_eur / nullif(prior_ttm_eur, 0) - 1) * 100, 1) as growth_pct
from revenue
order by ttm_eur desc;
