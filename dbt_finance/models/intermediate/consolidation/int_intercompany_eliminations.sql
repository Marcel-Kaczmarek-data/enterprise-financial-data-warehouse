-- Consolidation elimination entries in the group reporting currency (EUR), stored separately from
-- the standalone ledgers for auditability. Every elimination_id sums to exactly zero (tested).
--   IC_REVENUE_EXPENSE  (MOVEMENT)         Dr 4500 seller / Cr 6650 buyer / difference -> 8400
--   IC_BALANCES         (CLOSING_BALANCE)  Cr 1150 seller / Dr 2050 buyer / difference -> 1190
--   INVESTMENT_EQUITY   (CLOSING_BALANCE)  Cr 1700 parent / Dr 3000 child  / difference -> 3100
-- Scope: wholly owned subsidiaries (no non-controlling interests; see docs/financial-consolidation).
with positions as (
    select * from {{ ref('int_counterparty_balances') }}
),

pairs as (
    -- seller/buyer (or parent/child) pairs observed on either side
    select distinct
        case when group_account_code in ('4500', '1150', '1700') then entity_id else counterparty_entity_id end as side_a,
        case when group_account_code in ('4500', '1150', '1700') then counterparty_entity_id else entity_id end as side_b,
        case
            when group_account_code in ('4500', '6650') then 'IC_REVENUE_EXPENSE'
            when group_account_code in ('1150', '2050') then 'IC_BALANCES'
            else 'INVESTMENT_EQUITY'
        end as elimination_type,
        fiscal_period
    from positions
),

amounts as (
    select
        p.elimination_type,
        p.fiscal_period,
        p.side_a,
        p.side_b,
        -- side A: seller revenue (credit, negative) / IC receivable (debit) / investment (debit)
        coalesce(sum(case
            when p.elimination_type = 'IC_REVENUE_EXPENSE' and a.group_account_code = '4500' then a.movement_reporting
            when p.elimination_type = 'IC_BALANCES' and a.group_account_code = '1150' then a.closing_reporting
            when p.elimination_type = 'INVESTMENT_EQUITY' and a.group_account_code = '1700' then a.closing_reporting
        end), 0) as side_a_amount
    from pairs as p
    left join positions as a
        on a.entity_id = p.side_a and a.counterparty_entity_id = p.side_b and a.fiscal_period = p.fiscal_period
    group by 1, 2, 3, 4
),

with_b as (
    select
        am.*,
        coalesce(sum(case
            when am.elimination_type = 'IC_REVENUE_EXPENSE' and b.group_account_code = '6650' then b.movement_reporting
            when am.elimination_type = 'IC_BALANCES' and b.group_account_code = '2050' then b.closing_reporting
            when am.elimination_type = 'INVESTMENT_EQUITY' and b.group_account_code = '3000' then b.closing_reporting
        end), 0) as side_b_amount
    from amounts as am
    left join positions as b
        on b.entity_id = am.side_b and b.counterparty_entity_id = am.side_a and b.fiscal_period = am.fiscal_period
    group by am.elimination_type, am.fiscal_period, am.side_a, am.side_b, am.side_a_amount
),

entries as (
    select
        {{ surrogate_key(['elimination_type', 'fiscal_period', 'side_a', 'side_b']) }} as elimination_id,
        elimination_type,
        fiscal_period,
        side_a,
        side_b,
        side_a_amount,
        side_b_amount
    from with_b
    where side_a_amount <> 0 or side_b_amount <> 0
)

select
    elimination_id, elimination_type, fiscal_period, side_a as entity_id, side_b as counterparty_entity_id,
    case elimination_type when 'IC_REVENUE_EXPENSE' then '4500' when 'IC_BALANCES' then '1150' else '1700' end
        as group_account_code,
    case when elimination_type = 'IC_REVENUE_EXPENSE' then 'MOVEMENT' else 'CLOSING_BALANCE' end as measure,
    -side_a_amount as amount_reporting,
    'Eliminate ' || side_a || ' side' as line_description
from entries

union all

select
    elimination_id, elimination_type, fiscal_period, side_b, side_a,
    case elimination_type when 'IC_REVENUE_EXPENSE' then '6650' when 'IC_BALANCES' then '2050' else '3000' end,
    case when elimination_type = 'IC_REVENUE_EXPENSE' then 'MOVEMENT' else 'CLOSING_BALANCE' end,
    -side_b_amount,
    'Eliminate ' || side_b || ' side'
from entries

union all

select
    elimination_id, elimination_type, fiscal_period, side_a, side_b,
    case elimination_type when 'IC_REVENUE_EXPENSE' then '8400' when 'IC_BALANCES' then '1190' else '3100' end,
    case when elimination_type = 'IC_REVENUE_EXPENSE' then 'MOVEMENT' else 'CLOSING_BALANCE' end,
    side_a_amount + side_b_amount,
    'Elimination difference (FX / timing)'
from entries
where side_a_amount + side_b_amount <> 0
