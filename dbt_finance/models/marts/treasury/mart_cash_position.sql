-- Daily cash position by entity, bank account and currency, plus expected inflows/outflows.
-- Grain: balance_date x bank_account_id. Semi-additive (sum across accounts, not dates).
-- Expected flows (next 30 days) are operational estimates from open receivables/payables due
-- dates at the latest snapshot - clearly separated from booked balances.
with balances as (
    select * from {{ ref('fact_daily_cash_balances') }}
),

latest as (
    select max(snapshot_date) as d from {{ ref('fact_receivables_snapshot') }}
),

expected_in as (
    select entity_id, sum(outstanding_amount_reporting) as expected_inflows_30d
    from {{ ref('fact_receivables_snapshot') }}
    where snapshot_date = (select d from latest) and days_overdue between -30 and 0 and not is_intercompany
    group by 1
),

expected_out as (
    select entity_id, sum(outstanding_amount_reporting) as expected_outflows_30d
    from {{ ref('fact_payables_snapshot') }}
    where snapshot_date = (select d from latest) and days_overdue between -30 and 0 and not is_intercompany
    group by 1
)

select
    b.balance_date,
    b.fiscal_period,
    b.entity_id,
    e.entity_name,
    b.bank_account_id,
    ba.bank_name,
    ba.account_purpose,
    b.currency,
    b.gl_balance as book_balance,
    b.bank_balance,
    b.bank_minus_book,
    b.gl_balance_reporting as book_balance_reporting,
    case when b.balance_date = (select d from latest) then ei.expected_inflows_30d end as expected_inflows_30d_reporting,
    case when b.balance_date = (select d from latest) then eo.expected_outflows_30d end as expected_outflows_30d_reporting,
    '{{ var("group_reporting_currency") }}' as reporting_currency,
    {{ audit_columns() }}
from balances as b
left join {{ ref('dim_bank_account') }} as ba on b.bank_account_id = ba.bank_account_id
left join {{ ref('dim_legal_entity') }} as e on b.entity_id = e.entity_id
left join expected_in as ei on b.entity_id = ei.entity_id and ba.account_purpose = 'OPERATING' and b.currency = e.functional_currency
left join expected_out as eo on b.entity_id = eo.entity_id and ba.account_purpose = 'OPERATING' and b.currency = e.functional_currency
