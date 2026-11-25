-- Budget versus actual by version, scenario, entity, period, account and cost center (EUR).
-- Grain: budget_version x scenario x entity x fiscal_period x group account x cost center.
-- Favourable: revenue actual >= budget, cost actual <= budget. Percent variance is NULL when the
-- budget is zero (never a division error). YTD measures accumulate within the fiscal year.
with aligned as (
    select * from {{ ref('int_budget_actual_alignment') }}
),

coa as (
    select group_account_code, group_account_name, statement_line from {{ ref('group_chart_of_accounts') }}
)

select
    a.budget_version,
    a.scenario,
    a.entity_id,
    e.entity_name,
    a.fiscal_period,
    a.fiscal_year,
    a.group_account_code,
    c.group_account_name,
    c.statement_line,
    c.statement_line in ('Product revenue', 'Service revenue', 'Other operating revenue', 'Finance income') as is_revenue,
    a.cost_center_id,
    cc.department_id,
    cc.department_name,
    cc.functional_area,
    a.actual_amount_reporting,
    a.budget_amount_reporting,
    a.actual_amount_reporting - a.budget_amount_reporting as variance_reporting,
    {{ safe_divide('a.actual_amount_reporting - a.budget_amount_reporting', 'abs(a.budget_amount_reporting)') }}
        as variance_pct,
    {{ variance_is_favourable('a.actual_amount_reporting', 'a.budget_amount_reporting',
        "c.statement_line in ('Product revenue', 'Service revenue', 'Other operating revenue', 'Finance income')") }}
        as is_favourable,
    a.budget_amount_reporting - a.actual_amount_reporting as remaining_budget_reporting,
    {{ safe_divide('a.actual_amount_reporting', 'a.budget_amount_reporting') }} as budget_utilization,
    sum(a.actual_amount_reporting) over ytd as ytd_actual_reporting,
    sum(a.budget_amount_reporting) over ytd as ytd_budget_reporting,
    a.has_actual,
    a.has_budget,
    '{{ var("group_reporting_currency") }}' as reporting_currency,
    {{ audit_columns() }}
from aligned as a
left join coa as c on a.group_account_code = c.group_account_code
left join {{ ref('dim_cost_center') }} as cc on a.cost_center_id = cc.cost_center_id
left join {{ ref('dim_legal_entity') }} as e on a.entity_id = e.entity_id
window ytd as (
    partition by a.budget_version, a.scenario, a.entity_id, a.group_account_code, a.cost_center_id, a.fiscal_year
    order by a.fiscal_period rows between unbounded preceding and current row
)
