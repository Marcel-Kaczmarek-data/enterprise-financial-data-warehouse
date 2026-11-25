-- Grain: one allocation of a payment to an invoice or credit note. Supports one payment settling
-- many invoices and one invoice settled by many payments (partial settlements).
select
    a.allocation_id,
    a.payment_id,
    a.document_type,
    a.document_id,
    a.allocation_date,
    {{ fiscal_period('a.allocation_date') }} as fiscal_period,
    p.entity_id,
    p.payment_type,
    a.currency,
    a.allocated_amount,
    a.discount_amount,
    a.functional_amount_relieved,
    count(*) over (partition by a.payment_id) as allocations_in_payment,
    count(*) over (partition by a.document_type, a.document_id) as payments_for_document,
    {{ audit_columns() }}
from {{ ref('stg_erp__payment_allocations') }} as a
inner join {{ ref('stg_erp__payments') }} as p on a.payment_id = p.payment_id
