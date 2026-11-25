-- {{ config(severity='error', tags=['critical']) }}
-- Accounting period status changes must follow the allowed state machine
-- (financial-rules.yaml): OPEN->SOFT_CLOSED->CLOSED->REOPENED->CLOSED (SOFT_CLOSED->OPEN allowed).
select entity_id, fiscal_period, from_status, to_status, changed_at
from {{ ref('stg_erp__period_status_changes') }}
where not (
    (from_status is null and to_status = 'OPEN')
    or (from_status = 'OPEN' and to_status = 'SOFT_CLOSED')
    or (from_status = 'SOFT_CLOSED' and to_status in ('OPEN', 'CLOSED'))
    or (from_status = 'CLOSED' and to_status = 'REOPENED')
    or (from_status = 'REOPENED' and to_status in ('SOFT_CLOSED', 'CLOSED'))
)
