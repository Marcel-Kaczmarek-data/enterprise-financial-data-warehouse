-- {{ config(severity='warn', tags=['reconciliation']) }}
-- Gross invoiced revenue (mart_revenue_analysis) less credit-note revenue reversals must agree with
-- GL product + service revenue per entity and year in functional currency (0.1 % tolerance for the
-- per-line currency proration).
with mart as (
    select entity_id, fiscal_year, sum(revenue_functional) as invoiced
    from {{ ref('mart_revenue_analysis') }}
    group by 1, 2
),

gl as (
    select entity_id, fiscal_year,
        -sum(case when journal_type <> 'AR_CREDIT_NOTE' then signed_amount_functional else 0 end) as gl_invoiced
    from {{ ref('fact_general_ledger') }}
    where group_account_code in ('4000', '4100')
    group by 1, 2
)

select m.entity_id, m.fiscal_year, m.invoiced, g.gl_invoiced
from mart as m
inner join gl as g on m.entity_id = g.entity_id and m.fiscal_year = g.fiscal_year
where abs(m.invoiced - g.gl_invoiced) > abs(g.gl_invoiced) * 0.001
