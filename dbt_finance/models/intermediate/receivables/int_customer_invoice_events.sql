-- Dated settlement events per customer invoice, in invoice currency and functional currency.
-- Events: ISSUE (+), RECEIPT allocation (-), CREDIT_NOTE / WRITE_OFF (-), REFUND of a credit balance (+).
-- Historical outstanding as of any date = sum of events dated <= that date. The current ERP
-- invoice status is never used for historical reporting.
with invoices as (
    select * from {{ ref('stg_erp__customer_invoices') }} where not is_deleted
),

invoice_functional as (
    -- functional amount actually posted to AR for the invoice (source of truth for the subledger)
    select
        cast(source_document_id as bigint) as invoice_id,
        sum(signed_amount_functional) as functional_amount
    from {{ ref('fact_general_ledger') }}
    where source_document_type = 'CUSTOMER_INVOICE' and group_account_code in ('1100', '1150')
    group by 1
),

credit_notes as (
    select * from {{ ref('stg_erp__credit_notes') }}
),

allocations as (
    select * from {{ ref('stg_erp__payment_allocations') }}
)

select
    i.invoice_id,
    'ISSUE' as event_type,
    i.invoice_date as event_date,
    cast(i.invoice_id as varchar) as event_reference,
    i.invoice_amount as amount_transaction,
    f.functional_amount as amount_functional
from invoices as i
left join invoice_functional as f on i.invoice_id = f.invoice_id

union all

select
    a.document_id,
    'RECEIPT',
    a.allocation_date,
    cast(a.payment_id as varchar),
    -a.allocated_amount,
    -a.functional_amount_relieved
from allocations as a
where a.document_type = 'CUSTOMER_INVOICE'

union all

select
    c.invoice_id,
    case when c.reason_code = 'BAD_DEBT_WRITE_OFF' then 'WRITE_OFF' else 'CREDIT_NOTE' end,
    c.credit_note_date,
    c.credit_note_number,
    -c.credit_amount,
    -c.functional_amount
from credit_notes as c

union all

-- refund of a customer credit balance: allocation against the credit note (negative allocated amount)
select
    c.invoice_id,
    'REFUND',
    a.allocation_date,
    cast(a.payment_id as varchar),
    -a.allocated_amount,
    -a.functional_amount_relieved  -- stored as the (negative) credit balance relieved
from allocations as a
inner join credit_notes as c on a.document_type = 'CREDIT_NOTE' and a.document_id = c.credit_note_id
