-- Working-capital trend for the consolidated group: DSO, DPO and net working capital by month end.
-- Run against the published snapshot:
--   duckdb warehouse/local/published/finance_published.duckdb < sql/financial_analysis/01_working_capital_trend.sql
with balances as (
    select
        fiscal_period,
        sum(case when statement_line = 'Accounts receivable' then amount_reporting else 0 end) as receivables,
        sum(case when statement_line = 'Accounts payable' then amount_reporting else 0 end) as payables,
        sum(case when subsection = 'Current assets' then amount_reporting else 0 end) as current_assets,
        sum(case when subsection = 'Current liabilities' then amount_reporting else 0 end) as current_liabilities
    from finance_marts.mart_balance_sheet
    where reporting_scope = 'CONSOLIDATED'
    group by fiscal_period
),

revenue as (
    select
        fiscal_period,
        sum(case when statement_line = 'Total revenue' then amount_reporting else 0 end) as revenue,
        -sum(case when statement_line = 'Cost of goods sold' then amount_reporting else 0 end) as cogs
    from finance_marts.mart_profit_and_loss
    where reporting_scope = 'CONSOLIDATED'
    group by fiscal_period
),

rolling as (
    select
        fiscal_period,
        sum(revenue) over (order by fiscal_period rows between 2 preceding and current row) as revenue_3m,
        sum(cogs) over (order by fiscal_period rows between 2 preceding and current row) as cogs_3m
    from revenue
)

select
    b.fiscal_period,
    round(b.receivables, 0) as receivables_eur,
    round(b.payables, 0) as payables_eur,
    round(b.current_assets - b.current_liabilities, 0) as net_working_capital_eur,
    round(b.receivables / nullif(t.revenue_3m, 0) * 91, 1) as dso_days,
    round(b.payables / nullif(t.cogs_3m, 0) * 91, 1) as dpo_days_on_cogs
from balances as b
inner join rolling as t on b.fiscal_period = t.fiscal_period
order by b.fiscal_period;
