-- {{ config(severity='error', tags=['critical']) }}
-- No journal may be created after its period was CLOSED unless the period was REOPENED at that time.
with closes as (
    select entity_id, fiscal_period, min(changed_at) as first_closed_at
    from {{ ref('stg_erp__period_status_changes') }}
    where to_status = 'CLOSED'
    group by 1, 2
),

reopen_windows as (
    select o.entity_id, o.fiscal_period, o.changed_at as opened_at, min(c.changed_at) as reclosed_at
    from {{ ref('stg_erp__period_status_changes') }} as o
    inner join {{ ref('stg_erp__period_status_changes') }} as c
        on o.entity_id = c.entity_id and o.fiscal_period = c.fiscal_period
        and c.to_status = 'CLOSED' and c.changed_at > o.changed_at
    where o.to_status = 'REOPENED'
    group by 1, 2, 3
)

select h.journal_id, h.entity_id, h.fiscal_period, h.created_at
from {{ ref('stg_erp__journal_headers') }} as h
inner join closes as c on h.entity_id = c.entity_id and h.fiscal_period = c.fiscal_period
where h.posting_status = 'POSTED' and h.created_at > c.first_closed_at
    and not exists (
        select 1 from reopen_windows as r
        where r.entity_id = h.entity_id and r.fiscal_period = h.fiscal_period
            and h.created_at between r.opened_at and r.reclosed_at
    )
