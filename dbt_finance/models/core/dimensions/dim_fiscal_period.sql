-- Group fiscal periods (calendar months). Entities with a statutory APR-MAR year (India) report to
-- the group on calendar periods; their local fiscal year is exposed as local_fiscal_year.
select
    fiscal_period,
    min(fiscal_year) as fiscal_year,
    min(fiscal_quarter) as fiscal_quarter,
    min(calendar_month) as period_number,
    min(date_day) as period_start,
    max(date_day) as period_end,
    min(fiscal_year) * 100 + min(calendar_month) as period_key,
    case when min(calendar_month) >= 4 then min(fiscal_year) + 1 else min(fiscal_year) end as local_fiscal_year_apr_mar,
    max(is_quarter_end) as is_quarter_end_period,
    max(is_year_end) as is_year_end_period
from {{ ref('dim_date') }}
group by fiscal_period
