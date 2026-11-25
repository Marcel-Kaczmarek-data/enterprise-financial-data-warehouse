-- Supplier dimension (SCD Type 2 from the dbt snapshot). Bank details are excluded from core.
select
    {{ surrogate_key(['vendor_id', 'dbt_valid_from']) }} as vendor_key,
    vendor_id,
    vendor_number,
    vendor_name,
    vendor_category,
    country,
    currency,
    payment_terms_days,
    early_payment_discount_pct,
    early_payment_discount_days,
    vendor_status,
    is_intercompany,
    intercompany_entity_id,
    cast(dbt_valid_from as timestamp with time zone) as valid_from,
    coalesce(cast(dbt_valid_to as timestamp with time zone),
             cast('9999-12-31 00:00:00+00' as timestamp with time zone)) as valid_to,
    dbt_valid_to is null as is_current
from {{ ref('snap_erp__vendors') }}
