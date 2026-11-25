-- Period-average (income statement) and closing (balance sheet) rates per fiscal period.
-- rate_to_reporting = EUR per 1 unit of currency (inverse of the EUR-based publication).
{% set reporting = var('group_reporting_currency') %}

with monthly as (
    select
        {{ fiscal_period('rate_date') }} as fiscal_period,
        currency,
        max(case when rate_type = 'MONTH_AVG' then eur_to_currency end) as eur_to_currency_avg,
        max(case when rate_type = 'MONTH_END' then eur_to_currency end) as eur_to_currency_closing
    from {{ ref('int_fx_published_rates') }}
    where rate_type in ('MONTH_AVG', 'MONTH_END')
    group by 1, 2
)

select
    fiscal_period,
    currency,
    cast(round(1 / eur_to_currency_avg, 10) as decimal(24, 10)) as avg_rate_to_reporting,
    cast(round(1 / eur_to_currency_closing, 10) as decimal(24, 10)) as closing_rate_to_reporting
from monthly

union all

select distinct
    fiscal_period,
    '{{ reporting }}' as currency,
    cast(1 as decimal(24, 10)) as avg_rate_to_reporting,
    cast(1 as decimal(24, 10)) as closing_rate_to_reporting
from monthly
