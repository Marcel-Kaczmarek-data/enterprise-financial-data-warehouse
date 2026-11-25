-- Grain: one entity x fiscal period x group account x cost center x budget version x scenario.
-- Amounts are in natural presentation (revenue and cost positive), functional currency, and
-- translated to EUR at the period-average rate of the budget period.
with plans as (
    select * from {{ ref('stg_budget__plans') }}
),

rates as (
    select * from {{ ref('int_fx_rates_monthly') }}
),

budget_rates as (
    -- future periods have no published average yet: fall back to the latest available average
    select
        p.fiscal_period,
        c.currency,
        coalesce(r.avg_rate_to_reporting, last_r.avg_rate_to_reporting) as rate_to_reporting,
        r.avg_rate_to_reporting is null as is_projected_rate
    from (select distinct fiscal_period from plans) as p
    cross join (select distinct currency from plans) as c
    left join rates as r on p.fiscal_period = r.fiscal_period and c.currency = r.currency
    left join (
        select currency, avg_rate_to_reporting from rates
        qualify row_number() over (partition by currency order by fiscal_period desc) = 1
    ) as last_r on c.currency = last_r.currency
)

select
    p.budget_id,
    {{ surrogate_key(['p.entity_id', 'p.fiscal_period', 'p.account_code', 'p.cost_center_id', 'p.budget_version', 'p.scenario']) }}
        as budget_key,
    p.entity_id,
    p.fiscal_year,
    p.fiscal_period,
    p.account_code as group_account_code,
    g.statement_line,
    p.department_id,
    p.cost_center_id,
    p.budget_version,
    p.scenario,
    p.budget_amount,
    p.currency as functional_currency,
    {{ to_reporting('p.budget_amount', 'br.rate_to_reporting') }} as budget_amount_reporting,
    br.is_projected_rate,
    p.approval_status,
    p.approved_at,
    p.source_file,
    {{ audit_columns() }}
from plans as p
left join budget_rates as br on p.fiscal_period = br.fiscal_period and p.currency = br.currency
left join {{ ref('group_chart_of_accounts') }} as g on p.account_code = g.group_account_code
