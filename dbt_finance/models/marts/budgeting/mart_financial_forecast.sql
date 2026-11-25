-- Baseline financial forecast (consolidated, EUR): growth-adjusted seasonal naive.
--   forecast(m) = actual(m - 12) x growth, growth = sum(last 12 months) / sum(previous 12 months)
--   evaluated at the forecast origin.
-- Chronological evaluation: origin = last complete month - 6; the 6 holdout months are forecast
-- using ONLY data up to the origin (no future leakage). MAE and WAPE are reported per metric;
-- WAPE is NULL when actuals sum to zero. A forward forecast of 6 months is produced from the
-- latest origin. Statistical baseline only - the project's focus is the data platform.
-- Grain: metric x forecast_type x target_period.
with actuals as (
    select fiscal_period, 'REVENUE' as metric, revenue as value
    from {{ ref('mart_executive_financial_summary') }} where reporting_scope = 'CONSOLIDATED'
    union all
    select fiscal_period, 'OPERATING_EXPENSES', operating_expenses
    from {{ ref('mart_executive_financial_summary') }} where reporting_scope = 'CONSOLIDATED'
    union all
    select fiscal_period, 'OPERATING_CASH_FLOW', operating_cash_flow
    from {{ ref('mart_executive_financial_summary') }} where reporting_scope = 'CONSOLIDATED'
),

indexed as (
    select
        metric,
        fiscal_period,
        value,
        row_number() over (partition by metric order by fiscal_period) as idx
    from actuals
),

last_idx as (
    -- the latest period may be incomplete when the source cutoff is mid-month: use complete months
    select metric, max(idx) as max_idx from indexed group by 1
),

origins as (
    select metric, max_idx - 6 as origin_idx, 'BACKTEST' as forecast_type from last_idx
    union all
    select metric, max_idx, 'FORWARD' from last_idx
),

growth as (
    select
        o.metric,
        o.forecast_type,
        o.origin_idx,
        {{ safe_divide(
            'sum(case when i.idx between o.origin_idx - 11 and o.origin_idx then i.value end)',
            'sum(case when i.idx between o.origin_idx - 23 and o.origin_idx - 12 then i.value end)') }} as growth_factor
    from origins as o
    inner join indexed as i on o.metric = i.metric
    group by 1, 2, 3
),

horizon as (
    select h from (values (1), (2), (3), (4), (5), (6)) as t (h)
),

forecasts as (
    select
        g.metric,
        g.forecast_type,
        g.origin_idx,
        hz.h as horizon_months,
        g.origin_idx + hz.h as target_idx,
        base.value * g.growth_factor as forecast_value
    from growth as g
    cross join horizon as hz
    inner join indexed as base on g.metric = base.metric and base.idx = g.origin_idx + hz.h - 12
),

periods as (
    select fiscal_period, row_number() over (order by fiscal_period) as idx
    from {{ ref('dim_fiscal_period') }}
    where fiscal_period >= (select min(fiscal_period) from actuals)
),

scored as (
    select
        f.metric,
        f.forecast_type,
        op.fiscal_period as origin_period,
        tp.fiscal_period as target_period,
        f.horizon_months,
        round(f.forecast_value, 2) as forecast_value,
        a.value as actual_value,
        abs(f.forecast_value - a.value) as absolute_error
    from forecasts as f
    inner join periods as op on f.origin_idx = op.idx
    inner join periods as tp on f.target_idx = tp.idx
    left join indexed as a on f.metric = a.metric and f.target_idx = a.idx and f.forecast_type = 'BACKTEST'
)

select
    s.*,
    avg(s.absolute_error) over (partition by s.metric, s.forecast_type) as mae,
    {{ safe_divide('sum(s.absolute_error) over (partition by s.metric, s.forecast_type)',
                   'sum(abs(s.actual_value)) over (partition by s.metric, s.forecast_type)') }} as wape,
    'SEASONAL_NAIVE_GROWTH_v1' as model_version,
    current_date as generated_on,
    '{{ var("group_reporting_currency") }}' as reporting_currency,
    {{ audit_columns() }}
from scored as s
