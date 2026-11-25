-- Bank reconciliation summary per bank account and period-end:
-- book balance + reconciling items = bank balance, with match statistics.
-- Grain: bank_account_id x fiscal_period.
with items as (
    select * from {{ ref('int_bank_transaction_matching') }}
),

stats as (
    select
        bank_account_id,
        fiscal_period,
        count(*) filter (where item_side = 'BANK') as bank_lines,
        count(*) filter (where item_side = 'BANK' and match_status = 'MATCHED') as bank_lines_matched,
        count(*) filter (where match_status = 'OUTSTANDING_IN_TRANSIT') as items_in_transit,
        count(*) filter (where match_status = 'AMBIGUOUS_REVIEW') as items_for_review,
        count(*) filter (where match_status in ('UNMATCHED_LEDGER', 'UNMATCHED_BANK', 'POSSIBLE_DUPLICATE')) as exceptions
    from items
    group by 1, 2
),

period_end as (
    select bank_account_id, fiscal_period, entity_id, currency, book_balance, bank_balance
    from (
        select
            bank_account_id, fiscal_period, entity_id, currency, gl_balance as book_balance, bank_balance,
            row_number() over (partition by bank_account_id, fiscal_period order by balance_date desc) as rn
        from {{ ref('fact_daily_cash_balances') }}
    ) as x
    where rn = 1
)

select
    pe.bank_account_id,
    pe.entity_id,
    pe.fiscal_period,
    pe.currency,
    pe.book_balance,
    pe.bank_balance,
    pe.bank_balance - pe.book_balance as unexplained_difference_before_items,
    coalesce(s.bank_lines, 0) as bank_lines,
    coalesce(s.bank_lines_matched, 0) as bank_lines_matched,
    {{ safe_divide('s.bank_lines_matched', 's.bank_lines') }} as match_rate,
    coalesce(s.items_in_transit, 0) as items_in_transit,
    coalesce(s.items_for_review, 0) as items_for_review,
    coalesce(s.exceptions, 0) as exceptions,
    {{ audit_columns() }}
from period_end as pe
left join stats as s on pe.bank_account_id = s.bank_account_id and pe.fiscal_period = s.fiscal_period
