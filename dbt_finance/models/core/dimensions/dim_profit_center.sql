-- Profit centers (entity x product line), with an explicit unknown member for unassigned lines.
select
    {{ surrogate_key(['profit_center_id']) }} as profit_center_key,
    profit_center_id,
    profit_center_name,
    entity_id,
    product_line
from {{ ref('stg_erp__profit_centers') }}

union all

select
    {{ surrogate_key(["'-1'"]) }} as profit_center_key,
    '-1' as profit_center_id,
    'Unassigned' as profit_center_name,
    null as entity_id,
    'Unassigned' as product_line
