-- Intercompany positions per entity, counterparty, group account and period (EUR).
-- Covers IC revenue/expense (movements) and IC receivables/payables, investments and share capital
-- (closing balances). Grain: entity x counterparty x group account x fiscal period.
{% set ic_accounts = ['4500', '6650', '1150', '2050', '1700', '3000'] %}

with gl as (
    select *
    from {{ ref('fact_general_ledger') }}
    where group_account_code in ('{{ ic_accounts | join("', '") }}') and counterparty_entity_id is not null
),

movements as (
    select
        entity_id,
        counterparty_entity_id,
        group_account_code,
        fiscal_period,
        functional_currency,
        sum(signed_amount_functional) as movement_functional,
        sum(signed_amount_reporting) as movement_reporting
    from gl
    group by 1, 2, 3, 4, 5
),

keys as (
    select entity_id, counterparty_entity_id, group_account_code, functional_currency, min(fiscal_period) as first_period
    from movements
    group by 1, 2, 3, 4
),

grid as (
    select k.*, p.fiscal_period
    from keys as k
    inner join {{ ref('dim_fiscal_period') }} as p
        on p.fiscal_period >= k.first_period and p.fiscal_period <= (select max(fiscal_period) from gl)
),

cumulative as (
    select
        g.entity_id,
        g.counterparty_entity_id,
        g.group_account_code,
        g.fiscal_period,
        g.functional_currency,
        coalesce(m.movement_functional, 0) as movement_functional,
        coalesce(m.movement_reporting, 0) as movement_reporting,
        sum(coalesce(m.movement_functional, 0)) over w as closing_functional,
        sum(coalesce(m.movement_reporting, 0)) over w as cumulative_reporting_historical
    from grid as g
    left join movements as m
        on
            g.entity_id = m.entity_id and g.counterparty_entity_id = m.counterparty_entity_id
            and g.group_account_code = m.group_account_code and g.fiscal_period = m.fiscal_period
    window w as (
        partition by g.entity_id, g.counterparty_entity_id, g.group_account_code
        order by g.fiscal_period rows between unbounded preceding and current row
    )
)

select
    c.*,
    case
        when c.group_account_code in ('1150', '2050')
            then {{ to_reporting('c.closing_functional', 'r.closing_rate_to_reporting') }}
        else c.cumulative_reporting_historical
    end as closing_reporting
from cumulative as c
left join {{ ref('int_fx_rates_monthly') }} as r
    on c.fiscal_period = r.fiscal_period and c.functional_currency = r.currency
