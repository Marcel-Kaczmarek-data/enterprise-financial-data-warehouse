-- Global department master (grain: one department).
select
    {{ surrogate_key(['department_id']) }} as department_key,
    department_id,
    department_name,
    functional_area,
    case functional_area
        when 'OPERATIONS' then 'Cost of sales and operations'
        when 'SALES' then 'Sales'
        when 'MARKETING' then 'Marketing'
        when 'R&D' then 'Research and development'
        else 'General and administrative'
    end as functional_area_name
from {{ ref('stg_erp__departments') }}
