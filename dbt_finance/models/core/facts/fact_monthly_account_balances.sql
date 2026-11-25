-- Grain: one entity x local account x fiscal period (including periods without movements).
-- Semi-additive: closing balances may be summed across entities/accounts but NEVER across periods;
-- movements are additive across periods.
--
-- Reporting-currency translation (EUR), per group account translation_method:
--   CLOSING     balance sheet items: closing functional balance x closing rate of the period
--   HISTORICAL  equity and investments: cumulative movements at historical / average rates
--   AVERAGE     income statement: movements at period-average rate (cumulative kept for equity)
-- The translated trial balance does not balance by itself; the difference is the currency
-- translation adjustment (CTA), computed in int_translated_trial_balance.
with gl as (
    select * from {{ ref('fact_general_ledger') }}
),

movements as (
    select
        entity_id,
        account_id,
        fiscal_period,
        sum(debit_amount) as debit_functional,
        sum(credit_amount) as credit_functional,
        sum(signed_amount_functional) as movement_functional,
        sum(signed_amount_reporting) as movement_reporting_historical,
        count(*) as line_count
    from gl
    group by 1, 2, 3
),

accounts as (
    select
        m.entity_id,
        m.account_id,
        min(m.fiscal_period) as first_period
    from movements as m
    group by 1, 2
),

periods as (
    select fiscal_period
    from {{ ref('dim_fiscal_period') }}
    where fiscal_period <= (select max(fiscal_period) from gl)
),

grid as (
    select a.entity_id, a.account_id, p.fiscal_period
    from accounts as a
    inner join periods as p on p.fiscal_period >= a.first_period
),

mapping as (
    select * from {{ ref('int_account_mapping') }}
),

entities as (
    select entity_id, functional_currency from {{ ref('dim_legal_entity') }}
),

rates as (
    select * from {{ ref('int_fx_rates_monthly') }}
),

balances as (
    select
        g.entity_id,
        g.account_id,
        g.fiscal_period,
        coalesce(m.debit_functional, 0) as debit_functional,
        coalesce(m.credit_functional, 0) as credit_functional,
        coalesce(m.movement_functional, 0) as movement_functional,
        coalesce(m.movement_reporting_historical, 0) as movement_reporting_historical,
        coalesce(m.line_count, 0) as line_count,
        sum(coalesce(m.movement_functional, 0)) over (
            partition by g.entity_id, g.account_id order by g.fiscal_period
            rows between unbounded preceding and current row
        ) as closing_balance_functional,
        sum(coalesce(m.movement_reporting_historical, 0)) over (
            partition by g.entity_id, g.account_id order by g.fiscal_period
            rows between unbounded preceding and current row
        ) as cumulative_reporting_historical
    from grid as g
    left join movements as m
        on g.entity_id = m.entity_id and g.account_id = m.account_id and g.fiscal_period = m.fiscal_period
)

select
    {{ surrogate_key(['b.entity_id', 'b.account_id', 'b.fiscal_period']) }} as balance_key,
    b.entity_id,
    b.account_id,
    mp.local_account_code,
    mp.group_account_code,
    mp.statement,
    mp.statement_line,
    mp.translation_method,
    b.fiscal_period,
    e.functional_currency,
    b.closing_balance_functional - b.movement_functional as opening_balance_functional,
    b.debit_functional,
    b.credit_functional,
    b.movement_functional,
    b.closing_balance_functional,
    b.line_count,
    r.closing_rate_to_reporting,
    r.avg_rate_to_reporting,
    b.movement_reporting_historical as movement_reporting,
    case
        when mp.translation_method = 'CLOSING'
            then {{ to_reporting('b.closing_balance_functional', 'r.closing_rate_to_reporting') }}
        else b.cumulative_reporting_historical
    end as closing_balance_reporting,
    '{{ var("group_reporting_currency") }}' as reporting_currency,
    {{ audit_columns() }}
from balances as b
inner join mapping as mp on b.account_id = mp.account_id
inner join entities as e on b.entity_id = e.entity_id
left join rates as r on b.fiscal_period = r.fiscal_period and e.functional_currency = r.currency
