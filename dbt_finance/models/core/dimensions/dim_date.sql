-- Calendar dimension covering the full ledger range plus one year of forecast horizon.
with bounds as (
    select
        cast(date_trunc('year', min(posting_date)) as date) as start_date,
        cast(date_trunc('year', max(posting_date)) as date) + interval 2 year - interval 1 day as end_date
    from {{ ref('int_general_ledger_enriched') }}
),

spine as (
    {{ date_spine('(select start_date from bounds)', '(select end_date from bounds)') }}
)

select
    extract(year from date_day) * 10000 + extract(month from date_day) * 100 + extract(day from date_day) as date_key,
    date_day,
    extract(year from date_day) as calendar_year,
    extract(quarter from date_day) as calendar_quarter,
    extract(month from date_day) as calendar_month,
    monthname(date_day) as month_name,
    extract(day from date_day) as day_of_month,
    extract(isodow from date_day) as iso_day_of_week,
    extract(isodow from date_day) >= 6 as is_weekend,
    {{ fiscal_period('date_day') }} as fiscal_period,
    extract(year from date_day) as fiscal_year,
    'Q' || extract(quarter from date_day) as fiscal_quarter,
    cast(last_day(date_day) as date) = date_day as is_month_end,
    date_day = cast(date_trunc('quarter', date_day) + interval 3 month - interval 1 day as date) as is_quarter_end,
    extract(month from date_day) = 12 and extract(day from date_day) = 31 as is_year_end
from spine
