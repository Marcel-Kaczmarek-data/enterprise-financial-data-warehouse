-- Revenue by entity, period, product line, product, customer segment and country (EUR).
-- Grain: entity x fiscal_period x product x customer segment x customer country.
-- Built from invoice lines (net of tax): GROSS invoiced revenue before credit notes and write-offs,
-- which are analysed in fact_customer_invoices. GL net revenue = this - credit notes (tested).
with lines as (
    select
        i.entity_id,
        i.fiscal_period,
        i.customer_segment_at_invoice as customer_segment,
        i.customer_country,
        i.customer_id,
        l.product_id,
        l.line_amount,
        i.invoice_amount_functional,
        i.invoice_amount,
        i.functional_currency
    from {{ ref('stg_erp__customer_invoice_lines') }} as l
    inner join {{ ref('fact_customer_invoices') }} as i on l.invoice_id = i.invoice_id
    where not i.is_intercompany
),

converted as (
    -- line functional value = line share of the invoice functional value (excluding tax share)
    select
        ln.*,
        round(ln.line_amount * {{ safe_divide('ln.invoice_amount_functional', 'ln.invoice_amount') }}, 2) as line_amount_functional
    from lines as ln
)

select
    c.entity_id,
    e.entity_name,
    e.country_name as entity_country,
    e.region,
    c.fiscal_period,
    cast(substr(c.fiscal_period, 1, 4) as integer) as fiscal_year,
    p.product_line,
    c.product_id,
    p.product_name,
    p.revenue_type,
    coalesce(c.customer_segment, 'Unknown') as customer_segment,
    c.customer_country,
    count(distinct c.customer_id) as customers,
    sum(c.line_amount_functional) as revenue_functional,
    sum({{ to_reporting('c.line_amount_functional', 'r.avg_rate_to_reporting') }}) as revenue_reporting,
    '{{ var("group_reporting_currency") }}' as reporting_currency,
    {{ audit_columns() }}
from converted as c
left join {{ ref('dim_product') }} as p on c.product_id = p.product_id
left join {{ ref('dim_legal_entity') }} as e on c.entity_id = e.entity_id
left join {{ ref('int_fx_rates_monthly') }} as r on c.fiscal_period = r.fiscal_period and c.functional_currency = r.currency
group by 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12
