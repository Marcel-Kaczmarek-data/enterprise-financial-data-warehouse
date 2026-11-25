-- Executive KPI summary per reporting scope, entity and period (EUR).
-- Grain: reporting_scope x entity_id x fiscal_period. Every ratio is computed from aggregated
-- numerators and denominators of the same scope (never an average of entity percentages), and
-- returns NULL when the denominator is zero.
with pl as (
    select
        reporting_scope,
        entity_id,
        fiscal_period,
        max(case when statement_line = 'Total revenue' then amount_reporting end) as revenue,
        max(case when statement_line = 'Gross profit' then amount_reporting end) as gross_profit,
        max(case when statement_line = 'Total operating expenses' then -amount_reporting end) as operating_expenses,
        max(case when statement_line = 'EBITDA' then amount_reporting end) as ebitda,
        max(case when statement_line = 'Operating profit (EBIT)' then amount_reporting end) as ebit,
        max(case when statement_line = 'Net profit' then amount_reporting end) as net_profit,
        max(case when statement_line = 'Total revenue' then prior_year_amount_reporting end) as revenue_prior_year,
        max(case when statement_line = 'Total operating expenses' then -prior_year_amount_reporting end)
            as operating_expenses_prior_year
    from {{ ref('mart_profit_and_loss') }}
    group by 1, 2, 3
),

bs as (
    select
        reporting_scope,
        entity_id,
        fiscal_period,
        sum(case when statement_line = 'Cash and cash equivalents' then amount_reporting else 0 end) as cash,
        sum(case when statement_line = 'Accounts receivable' then amount_reporting else 0 end) as accounts_receivable,
        sum(case when statement_line = 'Inventory' then amount_reporting else 0 end) as inventory,
        sum(case when statement_line = 'Accounts payable' then amount_reporting else 0 end) as accounts_payable,
        sum(case when section = 'Assets' and is_current then amount_reporting else 0 end) as current_assets,
        sum(case when section = 'Liabilities' and is_current then amount_reporting else 0 end) as current_liabilities,
        sum(case when section = 'Assets' then amount_reporting else 0 end) as total_assets,
        sum(case when section = 'Liabilities' then amount_reporting else 0 end) as total_liabilities,
        sum(case when section = 'Equity' then amount_reporting else 0 end) as total_equity,
        sum(case when statement_line in ('Short-term debt', 'Long-term debt') then amount_reporting else 0 end) as total_debt
    from {{ ref('mart_balance_sheet') }}
    group by 1, 2, 3
),

cf as (
    select
        reporting_scope,
        entity_id,
        fiscal_period,
        sum(case when cash_flow_section = 'OPERATING' then amount_reporting else 0 end) as operating_cash_flow,
        sum(case when cash_flow_line = 'Purchase of property, plant and equipment' then -amount_reporting else 0 end)
            as capital_expenditure
    from {{ ref('mart_cash_flow') }}
    group by 1, 2, 3
),

budget as (
    select
        'STANDALONE' as reporting_scope,
        entity_id,
        fiscal_period,
        sum(case when is_revenue then budget_amount_reporting else 0 end) as budget_revenue,
        sum(case when not is_revenue then budget_amount_reporting else 0 end) as budget_expense,
        sum(case when is_revenue then actual_amount_reporting else 0 end) as budget_scope_actual_revenue,
        sum(case when not is_revenue then actual_amount_reporting else 0 end) as budget_scope_actual_expense
    from {{ ref('mart_budget_vs_actual') }}
    where budget_version = 'ORIGINAL' and scenario = 'BASE'
    group by 1, 2, 3
),

budget_all as (
    select * from budget
    union all
    select 'CONSOLIDATED', 'GROUP', fiscal_period, sum(budget_revenue), sum(budget_expense),
        sum(budget_scope_actual_revenue), sum(budget_scope_actual_expense)
    from budget
    group by 3
),

pl_trailing as (
    select
        pl.*,
        sum(pl.revenue) over w as revenue_trailing_3m,
        sum(pl.revenue) over w12 as revenue_ltm,
        sum(pl.net_profit) over w12 as net_profit_ltm
    from pl
    window
        w as (partition by reporting_scope, entity_id order by fiscal_period rows between 2 preceding and current row),
        w12 as (partition by reporting_scope, entity_id order by fiscal_period rows between 11 preceding and current row)
)

select
    t.reporting_scope,
    t.entity_id,
    t.fiscal_period,
    cast(substr(t.fiscal_period, 1, 4) as integer) as fiscal_year,
    t.revenue,
    t.gross_profit,
    {{ safe_divide('t.gross_profit', 't.revenue') }} as gross_margin,
    t.operating_expenses,
    t.ebitda,
    {{ safe_divide('t.ebitda', 't.revenue') }} as ebitda_margin,
    t.ebit,
    {{ safe_divide('t.ebit', 't.revenue') }} as operating_margin,
    t.net_profit,
    {{ safe_divide('t.net_profit', 't.revenue') }} as net_profit_margin,
    {{ safe_divide('t.revenue - t.revenue_prior_year', 'abs(t.revenue_prior_year)') }} as revenue_growth_yoy,
    {{ safe_divide('t.operating_expenses - t.operating_expenses_prior_year', 'abs(t.operating_expenses_prior_year)') }}
        as expense_growth_yoy,
    b.cash,
    b.accounts_receivable,
    b.inventory,
    b.accounts_payable,
    b.current_assets - b.current_liabilities as working_capital,
    {{ safe_divide('b.current_assets', 'b.current_liabilities') }} as current_ratio,
    {{ safe_divide('b.current_assets - b.inventory', 'b.current_liabilities') }} as quick_ratio,
    {{ safe_divide('b.total_debt', 'b.total_equity') }} as debt_to_equity,
    {{ safe_divide('b.accounts_receivable * 91', 't.revenue_trailing_3m') }} as days_sales_outstanding,
    {{ safe_divide('t.net_profit_ltm', 'b.total_assets') }} as return_on_assets_ltm,
    {{ safe_divide('t.net_profit_ltm', 'b.total_equity') }} as return_on_equity_ltm,
    b.total_assets,
    b.total_liabilities,
    b.total_equity,
    c.operating_cash_flow,
    c.capital_expenditure,
    c.operating_cash_flow - c.capital_expenditure as free_cash_flow,
    bu.budget_revenue,
    bu.budget_expense,
    bu.budget_scope_actual_revenue - bu.budget_revenue as revenue_budget_variance,
    bu.budget_expense - bu.budget_scope_actual_expense as expense_budget_variance,
    '{{ var("group_reporting_currency") }}' as reporting_currency,
    {{ audit_columns() }}
from pl_trailing as t
left join bs as b on t.reporting_scope = b.reporting_scope and t.entity_id = b.entity_id and t.fiscal_period = b.fiscal_period
left join cf as c on t.reporting_scope = c.reporting_scope and t.entity_id = c.entity_id and t.fiscal_period = c.fiscal_period
left join budget_all as bu
    on t.reporting_scope = bu.reporting_scope and t.entity_id = bu.entity_id and t.fiscal_period = bu.fiscal_period
