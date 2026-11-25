-- Daily conversion rates to the group reporting currency (EUR) for every calendar day.
-- Weekends/holidays use the most recent published SPOT within 5 days (financial-rules.yaml).
-- A day without a rate inside that window yields NO row; downstream relationship tests treat
-- that as a missing-rate failure. Rates are never defaulted to 1, except EUR -> EUR.
{% set reporting = var('group_reporting_currency') %}

with spot as (
    select * from {{ ref('int_fx_published_rates') }} where rate_type = 'SPOT'
),

spine as (
    {{ date_spine("(select min(rate_date) from " ~ ref('int_fx_published_rates') ~ ")",
                  "(select max(rate_date) + 45 from " ~ ref('int_fx_published_rates') ~ ")") }}
),

currencies as (
    select distinct currency from spot
),

filled as (
    select
        s.date_day,
        c.currency,
        p.rate_date as rate_date_used,
        p.eur_to_currency
    from spine as s
    cross join currencies as c
    inner join spot as p
        on
            p.currency = c.currency
            and p.rate_date between {{ add_days('s.date_day', -5) }} and s.date_day
    qualify row_number() over (partition by s.date_day, c.currency order by p.rate_date desc) = 1
)

select
    date_day,
    currency,
    rate_date_used,
    eur_to_currency,
    cast(round(1 / eur_to_currency, 10) as decimal(24, 10)) as rate_to_reporting,
    '{{ reporting }}' as reporting_currency
from filled

union all

select
    date_day,
    '{{ reporting }}' as currency,
    date_day as rate_date_used,
    cast(1 as decimal(24, 10)) as eur_to_currency,
    cast(1 as decimal(24, 10)) as rate_to_reporting,
    '{{ reporting }}' as reporting_currency
from spine
