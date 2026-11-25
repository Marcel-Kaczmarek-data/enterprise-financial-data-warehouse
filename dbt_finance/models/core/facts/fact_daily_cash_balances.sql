-- Grain: one bank account x calendar date. Semi-additive: sum across accounts, never across dates.
-- Ledger balance (book) vs bank balance (statement) in account currency, plus the EUR value of the
-- book balance at that day's spot rate. The difference is explained by reconciling items
-- (deposits/payments in transit) in int_bank_transaction_matching.
with accounts as (
    select * from {{ ref('stg_erp__bank_accounts') }}
),

gl_daily as (
    select
        ba.bank_account_id,
        f.posting_date as balance_date,
        sum(f.transaction_amount) as gl_movement,
        sum(f.signed_amount_functional) as gl_movement_functional
    from {{ ref('fact_general_ledger') }} as f
    inner join accounts as ba on f.account_id = ba.gl_account_id
    group by 1, 2
),

bank_daily as (
    select bank_account_id, balance_date, closing_balance from {{ ref('stg_bank__balances') }}
),

spine as (
    select a.bank_account_id, a.entity_id, a.currency, d.date_day as balance_date
    from accounts as a
    cross join (
        select date_day from {{ ref('dim_date') }}
        where date_day between (select min(posting_date) from {{ ref('fact_general_ledger') }})
            and (select max(posting_date) from {{ ref('fact_general_ledger') }})
    ) as d
),

running as (
    select
        s.bank_account_id,
        s.entity_id,
        s.currency,
        s.balance_date,
        coalesce(g.gl_movement, 0) as gl_movement,
        sum(coalesce(g.gl_movement, 0)) over w as gl_balance,
        sum(coalesce(g.gl_movement_functional, 0)) over w as gl_balance_functional,
        b.closing_balance as bank_balance
    from spine as s
    left join gl_daily as g on s.bank_account_id = g.bank_account_id and s.balance_date = g.balance_date
    left join bank_daily as b on s.bank_account_id = b.bank_account_id and s.balance_date = b.balance_date
    window w as (partition by s.bank_account_id order by s.balance_date rows between unbounded preceding and current row)
)

select
    r.bank_account_id,
    {{ surrogate_key(['r.bank_account_id']) }} as bank_account_key,
    r.entity_id,
    r.balance_date,
    {{ fiscal_period('r.balance_date') }} as fiscal_period,
    r.currency,
    r.gl_movement,
    r.gl_balance,
    r.gl_balance_functional,
    r.bank_balance,
    r.bank_balance - r.gl_balance as bank_minus_book,
    {{ to_reporting('r.gl_balance', 'fx.rate_to_reporting') }} as gl_balance_reporting,
    {{ audit_columns() }}
from running as r
left join {{ ref('int_fx_rates_daily') }} as fx on r.balance_date = fx.date_day and r.currency = fx.currency
