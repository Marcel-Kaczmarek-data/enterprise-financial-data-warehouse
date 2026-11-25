{% snapshot snap_erp__vendors %}
{#- SCD Type 2 for the supplier master. The ERP exposes current state only, so history is captured
    by this snapshot from the first warehouse load onward (timestamp strategy on updated_at).
    Payment-terms renegotiations in the source therefore appear as new snapshot versions. -#}
{{ config(unique_key='vendor_id', strategy='timestamp', updated_at='updated_at', invalidate_hard_deletes=True) }}

select
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
    updated_at
from {{ ref('stg_erp__vendors') }}

{% endsnapshot %}
