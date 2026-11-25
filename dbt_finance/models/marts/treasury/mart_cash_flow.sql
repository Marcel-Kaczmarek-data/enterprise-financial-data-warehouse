-- Direct-method cash flow statement.
-- Grain: reporting_scope x entity_id x fiscal_period x cash_flow_section x cash_flow_line.
-- Validation rows per scope/entity/period:
--   functional (STANDALONE): opening cash + flows + revaluation/conversion effects = closing cash
--   EUR: effect of exchange rates = closing - opening - net flows (translation residual), so the
--   group statement always reconciles; internal transfers are excluded from flows and intercompany
--   settlements are removed on consolidation (they are not external group cash flows).
with flows as (
    select
        entity_id,
        fiscal_period,
        cash_flow_section,
        cash_flow_line,
        sum(signed_amount_functional) as amount_functional,
        sum(signed_amount_reporting) as amount_reporting
    from {{ ref('int_cash_flow_classification') }}
    group by 1, 2, 3, 4
),

cash_balances as (
    select
        entity_id,
        fiscal_period,
        sum(closing_balance_functional) as closing_cash_functional,
        sum(closing_balance_reporting) as closing_cash_reporting
    from {{ ref('fact_monthly_account_balances') }}
    where group_account_code = '1010'
    group by 1, 2
),

migration_cash as (
    -- the OPENING (migration) journal is the opening balance, not a cash flow
    select entity_id, sum(signed_amount_functional) as functional, sum(signed_amount_reporting) as reporting
    from {{ ref('fact_general_ledger') }}
    where group_account_code = '1010' and journal_type = 'OPENING'
    group by 1
),

entity_periods as (
    select
        c.entity_id,
        c.fiscal_period,
        c.closing_cash_functional,
        c.closing_cash_reporting,
        coalesce(lag(c.closing_cash_functional) over w, m.functional, 0) as opening_cash_functional,
        coalesce(lag(c.closing_cash_reporting) over w, m.reporting, 0) as opening_cash_reporting
    from cash_balances as c
    left join migration_cash as m on c.entity_id = m.entity_id
    window w as (partition by c.entity_id order by c.fiscal_period)
),

standalone_flows as (
    select
        'STANDALONE' as reporting_scope, entity_id, fiscal_period, cash_flow_section, cash_flow_line,
        amount_functional, amount_reporting
    from flows
    where cash_flow_section in ('OPERATING', 'INVESTING', 'FINANCING')
),

standalone_fx as (
    -- EUR residual (translation) + functional non-flow items (revaluation, conversion differences)
    select
        'STANDALONE' as reporting_scope,
        ep.entity_id,
        ep.fiscal_period,
        'FX_EFFECT' as cash_flow_section,
        'Effect of exchange rate changes on cash' as cash_flow_line,
        ep.closing_cash_functional - ep.opening_cash_functional - coalesce(sum(sf.amount_functional), 0) as amount_functional,
        ep.closing_cash_reporting - ep.opening_cash_reporting - coalesce(sum(sf.amount_reporting), 0) as amount_reporting
    from entity_periods as ep
    left join standalone_flows as sf on ep.entity_id = sf.entity_id and ep.fiscal_period = sf.fiscal_period
    group by ep.entity_id, ep.fiscal_period, ep.closing_cash_functional, ep.opening_cash_functional,
        ep.closing_cash_reporting, ep.opening_cash_reporting
),

group_periods as (
    select
        fiscal_period,
        sum(opening_cash_reporting) as opening_cash_reporting,
        sum(closing_cash_reporting) as closing_cash_reporting
    from entity_periods
    group by 1
),

consolidated_flows as (
    select
        'CONSOLIDATED' as reporting_scope, 'GROUP' as entity_id, fiscal_period, cash_flow_section, cash_flow_line,
        cast(null as decimal(38, 4)) as amount_functional, sum(amount_reporting) as amount_reporting
    from standalone_flows
    where cash_flow_line <> 'Intercompany settlements'
    group by 1, 2, 3, 4, 5
),

consolidated_fx as (
    select
        'CONSOLIDATED', 'GROUP', g.fiscal_period, 'FX_EFFECT', 'Effect of exchange rate changes on cash',
        cast(null as decimal(38, 4)),
        g.closing_cash_reporting - g.opening_cash_reporting - coalesce(sum(c.amount_reporting), 0)
    from group_periods as g
    left join consolidated_flows as c on g.fiscal_period = c.fiscal_period
    group by g.fiscal_period, g.closing_cash_reporting, g.opening_cash_reporting
),

statement as (
    select * from standalone_flows
    union all select * from standalone_fx
    union all select * from consolidated_flows
    union all select * from consolidated_fx
)

select
    s.reporting_scope,
    s.entity_id,
    s.fiscal_period,
    cast(substr(s.fiscal_period, 1, 4) as integer) as fiscal_year,
    s.cash_flow_section,
    s.cash_flow_line,
    case s.cash_flow_section when 'OPERATING' then 1 when 'INVESTING' then 2 when 'FINANCING' then 3 else 4 end
        as section_order,
    s.amount_functional,
    s.amount_reporting,
    case when s.reporting_scope = 'STANDALONE' then ep.opening_cash_functional end as opening_cash_functional,
    case when s.reporting_scope = 'STANDALONE' then ep.closing_cash_functional end as closing_cash_functional,
    coalesce(ep.opening_cash_reporting, gp.opening_cash_reporting) as opening_cash_reporting,
    coalesce(ep.closing_cash_reporting, gp.closing_cash_reporting) as closing_cash_reporting,
    e.functional_currency,
    '{{ var("group_reporting_currency") }}' as reporting_currency,
    {{ audit_columns() }}
from statement as s
left join entity_periods as ep
    on s.reporting_scope = 'STANDALONE' and s.entity_id = ep.entity_id and s.fiscal_period = ep.fiscal_period
left join group_periods as gp on s.reporting_scope = 'CONSOLIDATED' and s.fiscal_period = gp.fiscal_period
left join {{ ref('dim_legal_entity') }} as e on s.entity_id = e.entity_id
