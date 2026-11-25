-- Balance sheet (point-in-time closing balances at each month end; never summed across periods).
-- Grain: reporting_scope x entity_id x fiscal_period x statement_line.
-- Equity presentation: Share capital (3000), Retained earnings (3100 + accumulated prior-year
-- results), Current-period earnings (year-to-date result), Currency translation adjustments (CTA).
-- signed_amount_reporting is debit-positive; per scope/entity/period the lines sum to exactly zero,
-- which is the accounting equation Assets = Liabilities + Equity (tested).
with ttb as (
    select * from {{ ref('int_translated_trial_balance') }}
),

coa as (
    select group_account_code, statement, statement_line from {{ ref('group_chart_of_accounts') }}
),

bs_accounts as (
    select t.entity_id, t.fiscal_period, c.statement_line,
        sum(t.closing_balance_functional) as signed_functional,
        sum(t.closing_balance_reporting) as signed_reporting
    from ttb as t
    inner join coa as c on t.group_account_code = c.group_account_code
    where c.statement = 'BALANCE_SHEET'
    group by 1, 2, 3
),

pl_balances as (
    -- cumulative P&L (inception to date) and year-to-date P&L, debit-positive
    select
        b.entity_id,
        b.fiscal_period,
        sum(b.closing_balance_functional) as pl_cumulative_functional,
        sum(b.closing_balance_reporting) as pl_cumulative_reporting,
        sum(sum(b.movement_functional)) over w as pl_ytd_functional,
        sum(sum(b.movement_reporting)) over w as pl_ytd_reporting
    from {{ ref('fact_monthly_account_balances') }} as b
    where b.statement = 'INCOME_STATEMENT'
    group by 1, 2
    window w as (partition by b.entity_id, substr(b.fiscal_period, 1, 4) order by b.fiscal_period
                 rows between unbounded preceding and current row)
),

standalone as (
    select entity_id, fiscal_period, statement_line, signed_functional, signed_reporting
    from bs_accounts
    where statement_line <> 'Retained earnings'

    union all

    select
        coalesce(a.entity_id, p.entity_id), coalesce(a.fiscal_period, p.fiscal_period), 'Retained earnings',
        coalesce(a.signed_functional, 0) + coalesce(p.pl_cumulative_functional - p.pl_ytd_functional, 0),
        coalesce(a.signed_reporting, 0) + coalesce(p.pl_cumulative_reporting - p.pl_ytd_reporting, 0)
    from (select * from bs_accounts where statement_line = 'Retained earnings') as a
    full outer join pl_balances as p on a.entity_id = p.entity_id and a.fiscal_period = p.fiscal_period

    union all

    select entity_id, fiscal_period, 'Current-period earnings', pl_ytd_functional, pl_ytd_reporting
    from pl_balances
),

eliminations as (
    select e.fiscal_period, c.statement_line, sum(e.amount_reporting) as signed_reporting
    from {{ ref('int_intercompany_eliminations') }} as e
    inner join coa as c on e.group_account_code = c.group_account_code
    where e.measure = 'CLOSING_BALANCE'
    group by 1, 2
),

combined as (
    select 'STANDALONE' as reporting_scope, entity_id, fiscal_period, statement_line,
        signed_functional, signed_reporting
    from standalone

    union all

    select 'CONSOLIDATED', 'GROUP', fiscal_period, statement_line, null, sum(signed_reporting)
    from (
        select fiscal_period, statement_line, signed_reporting from standalone
        union all
        select fiscal_period, statement_line, signed_reporting from eliminations
    ) as u
    group by 1, 2, 3, 4
),

lines as (
    select * from {{ ref('financial_statement_lines') }} where statement = 'BALANCE_SHEET'
),

grid as (
    select d.reporting_scope, d.entity_id, d.fiscal_period, l.*
    from (select distinct reporting_scope, entity_id, fiscal_period from combined) as d
    cross join lines as l
)

select
    g.reporting_scope,
    g.entity_id,
    g.fiscal_period,
    cast(substr(g.fiscal_period, 1, 4) as integer) as fiscal_year,
    p.is_quarter_end_period,
    p.is_year_end_period,
    g.section,
    g.subsection,
    g.statement_line,
    g.line_order,
    g.is_current,
    e.functional_currency,
    coalesce(c.signed_functional, case when g.reporting_scope = 'STANDALONE' then 0 end) as signed_amount_functional,
    coalesce(c.signed_reporting, 0) as signed_amount_reporting,
    coalesce(c.signed_functional, 0) * g.presentation_sign as amount_functional,
    coalesce(c.signed_reporting, 0) * g.presentation_sign as amount_reporting,
    '{{ var("group_reporting_currency") }}' as reporting_currency,
    sum(coalesce(c.signed_reporting, 0)) over (partition by g.reporting_scope, g.entity_id, g.fiscal_period)
        as accounting_equation_difference,
    {{ audit_columns() }}
from grid as g
left join combined as c
    on
        g.reporting_scope = c.reporting_scope and g.entity_id = c.entity_id
        and g.fiscal_period = c.fiscal_period and g.statement_line = c.statement_line
left join {{ ref('dim_legal_entity') }} as e on g.entity_id = e.entity_id
left join {{ ref('dim_fiscal_period') }} as p on g.fiscal_period = p.fiscal_period
