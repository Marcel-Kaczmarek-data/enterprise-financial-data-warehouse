-- Standalone trial balances translated to EUR, completed with the currency translation adjustment.
-- Grain: entity x group account x fiscal period (reporting currency).
--   * balance sheet accounts at closing rates; equity at historical rates; P&L cumulative at
--     average rates (the cumulative P&L becomes retained/current earnings on the balance sheet);
--   * CTA (group account 3200) = balancing figure so the translated trial balance sums to zero.
-- EUR-functional entities therefore always have CTA = 0 (tested in tests/financial).
with balances as (
    select
        entity_id,
        group_account_code,
        fiscal_period,
        sum(closing_balance_functional) as closing_balance_functional,
        sum(closing_balance_reporting) as closing_balance_reporting,
        sum(movement_reporting) as movement_reporting
    from {{ ref('fact_monthly_account_balances') }}
    group by 1, 2, 3
),

cta as (
    select
        entity_id,
        '3200' as group_account_code,
        fiscal_period,
        cast(0 as decimal(38, 4)) as closing_balance_functional,
        -sum(closing_balance_reporting) as closing_balance_reporting,
        cast(null as decimal(38, 4)) as movement_reporting
    from balances
    group by 1, 3
)

select
    b.*,
    'STANDALONE' as balance_origin
from balances as b

union all

select
    c.*,
    'TRANSLATION' as balance_origin
from cta as c
