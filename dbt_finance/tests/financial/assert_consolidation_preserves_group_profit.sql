-- {{ config(severity='error', tags=['critical']) }}
-- Intercompany eliminations remove internal revenue and cost but never change group profit:
-- consolidated net profit = sum of standalone net profit (EUR) for every period.
with standalone as (
    select fiscal_period, sum(amount_reporting) as net_profit
    from {{ ref('mart_profit_and_loss') }}
    where reporting_scope = 'STANDALONE' and statement_line = 'Net profit'
    group by 1
),

consolidated as (
    select fiscal_period, amount_reporting as net_profit
    from {{ ref('mart_profit_and_loss') }}
    where reporting_scope = 'CONSOLIDATED' and statement_line = 'Net profit'
)

select s.fiscal_period, s.net_profit as standalone_sum, c.net_profit as consolidated
from standalone as s
inner join consolidated as c on s.fiscal_period = c.fiscal_period
where abs(s.net_profit - c.net_profit) > 0.01
