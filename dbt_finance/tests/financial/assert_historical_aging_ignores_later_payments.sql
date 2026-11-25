-- {{ config(severity='error', tags=['critical']) }}
-- As-of correctness: an invoice that is fully paid today but whose first payment is dated after a
-- reporting date must appear in that reporting date's aging with its full open amount.
select s.snapshot_date, s.invoice_id
from {{ ref('fact_receivables_snapshot') }} as s
inner join {{ ref('fact_customer_invoices') }} as i on s.invoice_id = i.invoice_id
inner join (
    select invoice_id, min(event_date) as first_settlement
    from {{ ref('int_customer_invoice_events') }}
    where event_type <> 'ISSUE'
    group by 1
) as f on s.invoice_id = f.invoice_id
where f.first_settlement > s.snapshot_date and s.outstanding_amount <> i.invoice_amount
