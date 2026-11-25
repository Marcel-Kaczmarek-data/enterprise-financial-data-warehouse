-- Employee dimension, SCD Type 2 from the payroll system's effective-dated job history.
-- Personal names are deliberately NOT exposed in the core layer (payroll data minimisation);
-- authorised payroll roles query them in the restricted staging schema only.
with history as (
    select * from {{ ref('stg_payroll__job_history') }}
),

employees as (
    select * from {{ ref('stg_payroll__employees') }}
),

versions as (
    select
        employee_id,
        effective_from as valid_from,
        coalesce(
            lead(effective_from) over (partition by employee_id order by effective_from),
            cast('9999-12-31' as date)
        ) as valid_to,
        entity_id,
        department_id,
        cost_center_id,
        job_title,
        grade,
        annual_salary,
        change_reason
    from history
)

select
    {{ surrogate_key(['v.employee_id', 'v.valid_from']) }} as employee_key,
    v.employee_id,
    e.employee_number,
    v.entity_id,
    v.department_id,
    v.cost_center_id,
    v.job_title,
    v.grade,
    v.annual_salary,
    e.salary_currency,
    v.change_reason,
    e.hire_date,
    e.termination_date,
    v.valid_from,
    v.valid_to,
    v.valid_to = cast('9999-12-31' as date) as is_current
from versions as v
left join employees as e on v.employee_id = e.employee_id
