-- Grain: one employee x pay period. Restricted: payroll amounts are classified PAYROLL and are
-- exposed to BI only aggregated by cost center (see mart_department_performance).
select
    t.payroll_line_id,
    t.payroll_run_id,
    t.employee_id,
    e.employee_key,
    t.entity_id,
    t.cost_center_id,
    t.department_id,
    t.pay_period as fiscal_period,
    t.pay_date,
    t.currency,
    t.gross_salary,
    t.employer_contributions,
    t.gross_salary + t.employer_contributions as total_employment_cost,
    t.employee_tax_withheld,
    t.expense_reimbursement,
    t.net_pay,
    {{ to_reporting('t.gross_salary + t.employer_contributions', 'r.avg_rate_to_reporting') }} as total_employment_cost_reporting,
    t.journal_id,
    {{ audit_columns() }}
from {{ ref('stg_payroll__transactions') }} as t
left join {{ ref('dim_employee') }} as e
    on t.employee_id = e.employee_id and t.pay_date >= e.valid_from and t.pay_date < e.valid_to
left join {{ ref('int_fx_rates_monthly') }} as r on t.pay_period = r.fiscal_period and t.currency = r.currency
