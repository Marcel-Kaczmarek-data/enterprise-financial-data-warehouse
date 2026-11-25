-- Product and service catalogue (grain: one product), plus the intercompany service pseudo-product.
select
    {{ surrogate_key(['product_id']) }} as product_key,
    product_id,
    product_name,
    product_line,
    revenue_type,
    list_price_eur,
    standard_cost_ratio
from {{ ref('stg_erp__products') }}

union all

select
    {{ surrogate_key(["'IC-SERVICE'"]) }},
    'IC-SERVICE',
    'Intercompany service charge',
    'Intercompany',
    'SERVICE',
    cast(0 as decimal(19, 4)),
    cast(0 as decimal(18, 4))
