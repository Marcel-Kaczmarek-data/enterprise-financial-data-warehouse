-- {{ config(severity='error', tags=['critical']) }}
-- Standalone, functional currency: opening cash + operating + investing + financing flows
-- + non-flow items (revaluation, FX conversion differences on internal transfers) = closing cash.
-- The FX-effect line must equal exactly those non-flow items (it is not allowed to absorb errors).
with statement as (
    select entity_id, fiscal_period,
        sum(case when cash_flow_section = 'FX_EFFECT' then amount_functional else 0 end) as fx_line
    from {{ ref('mart_cash_flow') }}
    where reporting_scope = 'STANDALONE'
    group by 1, 2
),

non_flows as (
    select entity_id, fiscal_period, sum(signed_amount_functional) as non_flow_items
    from {{ ref('int_cash_flow_classification') }}
    where cash_flow_section in ('INTERNAL_TRANSFER', 'FX_EFFECT')
    group by 1, 2
)

select s.entity_id, s.fiscal_period, s.fx_line, n.non_flow_items
from statement as s
left join non_flows as n on s.entity_id = n.entity_id and s.fiscal_period = n.fiscal_period
where abs(s.fx_line - coalesce(n.non_flow_items, 0)) > 0.005
