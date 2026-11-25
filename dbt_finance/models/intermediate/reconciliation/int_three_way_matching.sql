-- Three-way match: purchase order line vs goods receipt vs supplier invoice line.
-- Line-level results for PO-backed invoices plus invoice-level controls:
--   MATCHED, PRICE_VARIANCE (> tolerance), QUANTITY_VARIANCE (billed > received),
--   MISSING_GOODS_RECEIPT, NO_PURCHASE_ORDER (inventory invoice without PO),
--   DUPLICATE_INVOICE (same supplier + invoice number) - CRITICAL when the duplicate was paid.
{% set price_tol = var('three_way_price_tolerance_pct') %}

with invoice_lines as (
    select l.*, i.vendor_id, i.entity_id, i.vendor_invoice_number, i.invoice_date, i.currency,
        i.purchase_order_id, i.journal_id, i.expense_category
    from {{ ref('stg_erp__vendor_invoice_lines') }} as l
    inner join {{ ref('stg_erp__vendor_invoices') }} as i on l.vendor_invoice_id = i.vendor_invoice_id
),

po_lines as (
    select * from {{ ref('stg_erp__purchase_order_lines') }}
),

receipts as (
    select po_line_id, sum(quantity_received) as quantity_received, max(receipt_date) as last_receipt_date
    from {{ ref('stg_erp__goods_receipts') }}
    group by 1
),

line_matches as (
    select
        il.vendor_invoice_id,
        il.vendor_invoice_line_id,
        il.entity_id,
        il.vendor_id,
        il.purchase_order_id,
        il.po_line_id,
        il.invoice_date,
        il.currency,
        il.quantity as invoiced_quantity,
        il.unit_price as invoiced_unit_price,
        po.quantity as ordered_quantity,
        po.unit_price as ordered_unit_price,
        r.quantity_received,
        il.line_amount as invoiced_amount,
        case
            when r.po_line_id is null then 'MISSING_GOODS_RECEIPT'
            when il.quantity > r.quantity_received then 'QUANTITY_VARIANCE'
            when abs(il.unit_price - po.unit_price) > po.unit_price * {{ price_tol }} / 100 then 'PRICE_VARIANCE'
            else 'MATCHED'
        end as match_status,
        case
            when r.po_line_id is null then il.line_amount
            when il.quantity > r.quantity_received then (il.quantity - r.quantity_received) * il.unit_price
            else (il.unit_price - po.unit_price) * il.quantity
        end as discrepancy_amount
    from invoice_lines as il
    inner join po_lines as po on il.po_line_id = po.po_line_id
    left join receipts as r on il.po_line_id = r.po_line_id
),

duplicates as (
    select
        i.vendor_invoice_id,
        i.vendor_id,
        i.entity_id,
        i.invoice_date,
        i.currency,
        i.invoice_amount,
        i.journal_id is not null as was_posted,
        i.payment_status,
        count(*) over (partition by i.vendor_id, i.vendor_invoice_number) as occurrences,
        row_number() over (partition by i.vendor_id, i.vendor_invoice_number order by i.created_at) as occurrence_rank
    from {{ ref('stg_erp__vendor_invoices') }} as i
    where not i.is_intercompany
),

no_po as (
    select vendor_invoice_id, vendor_id, entity_id, invoice_date, currency, invoice_amount
    from {{ ref('stg_erp__vendor_invoices') }}
    where expense_category = 'INVENTORY' and purchase_order_id is null
)

select
    {{ surrogate_key(['vendor_invoice_line_id']) }} as match_id,
    'LINE' as check_level,
    vendor_invoice_id, vendor_invoice_line_id, entity_id, vendor_id, purchase_order_id, invoice_date, currency,
    match_status,
    case when match_status = 'MATCHED' then 0 else round(discrepancy_amount, 2) end as discrepancy_amount,
    case when match_status = 'MATCHED' then 'INFO' else 'WARNING' end as severity,
    case match_status
        when 'MISSING_GOODS_RECEIPT' then 'Invoice billed before any goods receipt was recorded'
        when 'QUANTITY_VARIANCE' then 'Billed quantity exceeds received quantity'
        when 'PRICE_VARIANCE' then 'Unit price differs from PO price beyond tolerance'
        else 'PO, receipt and invoice agree'
    end as explanation
from line_matches

union all

select
    {{ surrogate_key(['vendor_invoice_id', "'DUP'"]) }},
    'INVOICE',
    vendor_invoice_id, null, entity_id, vendor_id, null, invoice_date, currency,
    'DUPLICATE_INVOICE',
    invoice_amount,
    case when was_posted and payment_status = 'PAID' then 'CRITICAL' else 'WARNING' end,
    case when was_posted and payment_status = 'PAID'
        then 'Duplicate supplier invoice was posted and PAID - recover from supplier'
        else 'Duplicate supplier invoice detected (blocked before payment)' end
from duplicates
where occurrences > 1 and occurrence_rank > 1

union all

select
    {{ surrogate_key(['vendor_invoice_id', "'NOPO'"]) }},
    'INVOICE',
    vendor_invoice_id, null, entity_id, vendor_id, null, invoice_date, currency,
    'NO_PURCHASE_ORDER',
    invoice_amount,
    'WARNING',
    'Inventory invoice received without a purchase order (unauthorized purchase)'
from no_po
