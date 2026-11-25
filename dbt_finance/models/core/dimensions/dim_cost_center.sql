-- Cost center dimension with department and functional area (one row per cost center).
-- Grain: one cost center (entity x department).
with cost_centers as (
    select * from {{ ref('stg_erp__cost_centers') }}
),

departments as (
    select * from {{ ref('stg_erp__departments') }}
)

select
    {{ surrogate_key(['cc.cost_center_id']) }} as cost_center_key,
    cc.cost_center_id,
    cc.cost_center_name,
    cc.entity_id,
    cc.department_id,
    d.department_name,
    d.functional_area,
    cc.is_active
from cost_centers as cc
left join departments as d on cc.department_id = d.department_id
