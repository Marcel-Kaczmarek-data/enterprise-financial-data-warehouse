-- Dated settlement events per posted supplier invoice (positive = liability outstanding).
-- The liability exists from the GL posting date (receipt), not the supplier's invoice date, so the
-- ISSUE event is dated by the posting journal; otherwise received-late invoices open in the subledger
-- before the GL and the control account does not tie at month end.
-- Blocked duplicates are never posted to the GL (journal_id is null) and carry no liability.
with invoices as (
    select * from {{ ref('stg_erp__vendor_invoices') }} where journal_id is not null
),

invoice_functional as (
    select
        cast(source_document_id as bigint) as vendor_invoice_id,
        -sum(signed_amount_functional) as functional_amount,
        min(posting_date) as posting_date
    from {{ ref('fact_general_ledger') }}
    where source_document_type = 'VENDOR_INVOICE' and group_account_code in ('2000', '2050')
    group by 1
)

select
    i.vendor_invoice_id,
    'ISSUE' as event_type,
    coalesce(f.posting_date, i.invoice_date) as event_date,
    i.invoice_amount as amount_transaction,
    f.functional_amount as amount_functional
from invoices as i
left join invoice_functional as f on i.vendor_invoice_id = f.vendor_invoice_id

union all

select
    a.document_id,
    'PAYMENT',
    a.allocation_date,
    -(a.allocated_amount + a.discount_amount),
    -a.functional_amount_relieved
from {{ ref('stg_erp__payment_allocations') }} as a
where a.document_type = 'VENDOR_INVOICE'
