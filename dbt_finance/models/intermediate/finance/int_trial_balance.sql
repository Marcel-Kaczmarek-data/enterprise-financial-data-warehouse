-- Standalone trial balance per entity and period in functional currency, with group mapping.
-- Opening + debits - credits = closing must hold for every line (tested), and the sum of closing
-- balances per entity and period must be exactly zero (double-entry, tested).
select
    entity_id,
    fiscal_period,
    account_id,
    local_account_code,
    group_account_code,
    statement,
    statement_line,
    functional_currency,
    opening_balance_functional,
    debit_functional,
    credit_functional,
    closing_balance_functional,
    case when closing_balance_functional >= 0 then closing_balance_functional else 0 end as closing_debit_balance,
    case when closing_balance_functional < 0 then -closing_balance_functional else 0 end as closing_credit_balance
from {{ ref('fact_monthly_account_balances') }}
