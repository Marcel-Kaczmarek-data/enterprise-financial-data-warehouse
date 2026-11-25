-- Trial balance by entity, local account and period (functional currency), with the group mapping.
-- Business purpose: month-end review and audit; debits must equal credits per entity and period.
select
    t.entity_id,
    t.fiscal_period,
    t.account_id,
    t.local_account_code,
    a.local_account_name,
    t.group_account_code,
    a.group_account_name,
    t.statement,
    t.statement_line,
    t.functional_currency,
    t.opening_balance_functional,
    t.debit_functional,
    t.credit_functional,
    t.closing_balance_functional,
    t.closing_debit_balance,
    t.closing_credit_balance,
    sum(t.closing_balance_functional) over (partition by t.entity_id, t.fiscal_period) as entity_period_imbalance,
    {{ audit_columns() }}
from {{ ref('int_trial_balance') }} as t
left join {{ ref('int_account_mapping') }} as a on t.account_id = a.account_id
