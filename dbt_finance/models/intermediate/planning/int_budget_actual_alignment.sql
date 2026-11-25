-- Actuals aligned to the budget grain: entity x fiscal period x group account x cost center.
-- Actuals are aggregated FIRST (never joined at journal-line grain), which prevents duplicating
-- monthly budget amounts across many transactions. Natural sign: revenue and cost positive.
-- Intercompany charges, FX results, disposals and income tax are outside the budget scope.
with actuals as (
    select
        entity_id,
        fiscal_period,
        group_account_code,
        cost_center_id,
        sum(case when statement_line in ('Product revenue', 'Service revenue', 'Other operating revenue', 'Finance income')
            then -signed_amount_functional else signed_amount_functional end) as actual_amount,
        sum(case when statement_line in ('Product revenue', 'Service revenue', 'Other operating revenue', 'Finance income')
            then -signed_amount_reporting else signed_amount_reporting end) as actual_amount_reporting
    from {{ ref('fact_general_ledger') }}
    where statement = 'INCOME_STATEMENT'
        and group_account_code not in ('4500', '6650', '8200', '8350', '8400', '9000')
    group by 1, 2, 3, 4
),

budgets as (
    select * from {{ ref('fact_budgets') }}
),

versions as (
    select distinct budget_version, scenario from budgets
),

budget_keys as (
    select distinct entity_id, fiscal_period, group_account_code, cost_center_id from budgets
),

all_keys as (
    select entity_id, fiscal_period, group_account_code, cost_center_id from actuals
    union
    select entity_id, fiscal_period, group_account_code, cost_center_id from budget_keys
)

select
    k.entity_id,
    k.fiscal_period,
    cast(substr(k.fiscal_period, 1, 4) as integer) as fiscal_year,
    k.group_account_code,
    k.cost_center_id,
    v.budget_version,
    v.scenario,
    coalesce(a.actual_amount, 0) as actual_amount,
    coalesce(a.actual_amount_reporting, 0) as actual_amount_reporting,
    coalesce(b.budget_amount, 0) as budget_amount,
    coalesce(b.budget_amount_reporting, 0) as budget_amount_reporting,
    a.entity_id is not null as has_actual,
    b.budget_id is not null as has_budget
from all_keys as k
cross join versions as v
left join actuals as a
    on
        k.entity_id = a.entity_id and k.fiscal_period = a.fiscal_period
        and k.group_account_code = a.group_account_code and k.cost_center_id = a.cost_center_id
left join budgets as b
    on
        k.entity_id = b.entity_id and k.fiscal_period = b.fiscal_period
        and k.group_account_code = b.group_account_code and k.cost_center_id = b.cost_center_id
        and v.budget_version = b.budget_version and v.scenario = b.scenario
where a.entity_id is not null or b.budget_id is not null
