-- Legal entities with their consolidation path (recursive parent-child hierarchy).
-- All subsidiaries are wholly owned in the core scope (ownership_percentage = 100).
with recursive entities as (
    select * from {{ ref('stg_erp__legal_entities') }}
),

hierarchy as (
    select
        entity_id,
        parent_entity_id,
        entity_id as root_entity_id,
        0 as hierarchy_depth,
        cast(entity_id as varchar) as consolidation_path
    from entities
    where parent_entity_id is null

    union all

    select
        e.entity_id,
        e.parent_entity_id,
        h.root_entity_id,
        h.hierarchy_depth + 1,
        h.consolidation_path || ' > ' || e.entity_id
    from entities as e
    inner join hierarchy as h on e.parent_entity_id = h.entity_id
),

countries as (
    select * from (values
        ('NL', 'Netherlands', 'Europe'), ('DE', 'Germany', 'Europe'), ('FR', 'France', 'Europe'),
        ('IE', 'Ireland', 'Europe'), ('GB', 'United Kingdom', 'Europe'), ('CH', 'Switzerland', 'Europe'),
        ('SE', 'Sweden', 'Europe'), ('US', 'United States', 'North America'), ('CA', 'Canada', 'North America'),
        ('JP', 'Japan', 'Asia'), ('SG', 'Singapore', 'Asia'), ('IN', 'India', 'Asia')
    ) as t (country_code, country_name, region)
)

select
    {{ surrogate_key(['e.entity_id']) }} as entity_key,
    e.entity_id,
    e.entity_name,
    e.parent_entity_id,
    h.root_entity_id,
    h.hierarchy_depth,
    h.consolidation_path,
    e.entity_type,
    e.country as country_code,
    c.country_name,
    c.region,
    e.functional_currency,
    e.reporting_currency,
    e.fiscal_calendar,
    e.ownership_percentage,
    'FULL' as consolidation_method,
    e.effective_from,
    e.effective_to
from entities as e
left join hierarchy as h on e.entity_id = h.entity_id
left join countries as c on e.country = c.country_code
