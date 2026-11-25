-- Customer dimension, SCD Type 2 on segment / industry / country / status.
-- History comes from the CRM field-history log (effective-dated), so it is complete from the start
-- of the data range rather than only from the first warehouse load. Each version is valid in
-- [valid_from, valid_to); the current version has valid_to = 9999-12-31 and is_current = true.
-- Facts join on (customer_id, event timestamp) to get the version valid at the time of the event.
with history as (
    select * from {{ ref('stg_crm__customer_history') }}
),

current_master as (
    select * from {{ ref('stg_crm__customers') }}
),

versions as (
    select
        h.customer_id,
        h.valid_from,
        coalesce(
            lead(h.valid_from) over (partition by h.customer_id order by h.valid_from),
            cast('9999-12-31 00:00:00+00' as timestamp with time zone)
        ) as valid_to,
        h.segment,
        h.industry,
        h.country,
        h.customer_status,
        h.change_reason
    from history as h
)

select
    {{ surrogate_key(['v.customer_id', 'v.valid_from']) }} as customer_key,
    v.customer_id,
    c.customer_number,
    c.customer_name,
    c.home_entity_id,
    v.segment,
    v.industry,
    v.country,
    v.customer_status,
    v.change_reason,
    v.valid_from,
    v.valid_to,
    v.valid_to = cast('9999-12-31 00:00:00+00' as timestamp with time zone) as is_current
from versions as v
left join current_master as c on v.customer_id = c.customer_id

union all

-- Unknown member for intercompany receivable accounts and late-arriving customers.
select
    {{ surrogate_key(["'-1'"]) }}, -1, 'UNKNOWN', 'Unknown / intercompany customer', null, 'Unknown', 'Unknown',
    null, 'ACTIVE', 'Unknown member', cast('1900-01-01 00:00:00+00' as timestamp with time zone),
    cast('9999-12-31 00:00:00+00' as timestamp with time zone), true
