-- Cost center and department performance: expenses by statement line, payroll cost and headcount.
-- Grain: entity x fiscal_period x cost center x statement_line (P&L cost lines, EUR).
-- Payroll is shown only aggregated per cost center (individual salaries stay restricted).
with costs as (
    select
        entity_id,
        fiscal_period,
        cost_center_id,
        statement_line,
        sum(signed_amount_reporting) as expense_reporting
    from {{ ref('fact_general_ledger') }}
    where statement = 'INCOME_STATEMENT'
        and statement_line not in ('Product revenue', 'Service revenue', 'Other operating revenue',
                                   'Finance income', 'Income tax expense')
    group by 1, 2, 3, 4
),

headcount as (
    select cost_center_id, fiscal_period, count(distinct employee_id) as headcount,
        sum(total_employment_cost_reporting) as payroll_cost_reporting
    from {{ ref('fact_payroll') }}
    group by 1, 2
)

select
    c.entity_id,
    c.fiscal_period,
    cast(substr(c.fiscal_period, 1, 4) as integer) as fiscal_year,
    c.cost_center_id,
    cc.cost_center_name,
    cc.department_id,
    cc.department_name,
    cc.functional_area,
    c.statement_line,
    c.expense_reporting,
    h.headcount,
    h.payroll_cost_reporting,
    '{{ var("group_reporting_currency") }}' as reporting_currency,
    {{ audit_columns() }}
from costs as c
left join {{ ref('dim_cost_center') }} as cc on c.cost_center_id = cc.cost_center_id
left join headcount as h
    on c.cost_center_id = h.cost_center_id and c.fiscal_period = h.fiscal_period
    and c.statement_line = 'Salaries and benefits'
