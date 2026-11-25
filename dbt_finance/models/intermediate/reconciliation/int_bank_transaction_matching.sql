-- Bank reconciliation engine: matches ledger cash items to bank statement lines.
-- Rules, in priority order (each item is matched at most once):
--   R1 BANK_ORIGINATED   GL BANK journal posted from a bank line (source document = bank txn id)
--   R2 EXACT_REFERENCE   same bank account, reference and amount
--   R3 AMOUNT_DATE       same account and amount, value date within +/- N days, and the
--                        candidate is UNIQUE on both sides (ambiguous candidates are NOT matched)
-- Unmatched results:
--   OUTSTANDING_IN_TRANSIT  ledger item dated within N days of the latest bank statement date
--   OUTSTANDING_NOT_YET_BOOKED bank line within N days of the ledger horizon (booking pending)
--   AMBIGUOUS_REVIEW        several equally valid candidates: routed to the review queue
--   POSSIBLE_DUPLICATE      bank line identical to another bank line on the same day
--   UNMATCHED_LEDGER / UNMATCHED_BANK  exceptions requiring investigation
{% set tol = var('bank_match_date_tolerance_days') %}

with gl_items as (
    select
        f.journal_id,
        ba.bank_account_id,
        min(f.entity_id) as entity_id,
        min(f.posting_date) as posting_date,
        min(f.journal_type) as journal_type,
        min(f.source_document_type) as source_document_type,
        min(f.source_document_id) as source_document_id,
        coalesce(min(p.bank_reference), min(f.reference_number)) as reference,
        sum(f.transaction_amount) as amount
    from {{ ref('fact_general_ledger') }} as f
    inner join {{ ref('stg_erp__bank_accounts') }} as ba on f.account_id = ba.gl_account_id
    left join {{ ref('stg_erp__payments') }} as p on f.journal_id = p.journal_id
    where f.group_account_code = '1010' and f.journal_type not in ('OPENING', 'FX_REVALUATION')
    group by 1, 2
    having sum(f.transaction_amount) <> 0
),

bank as (
    select * from {{ ref('fact_bank_transactions') }}
),

r1 as (
    select g.journal_id, g.bank_account_id, b.bank_transaction_id, 'BANK_ORIGINATED' as match_rule
    from gl_items as g
    inner join bank as b
        on g.source_document_type = 'BANK_TRANSACTION' and g.source_document_id = b.bank_transaction_id
),

r2_candidates as (
    select g.journal_id, g.bank_account_id, b.bank_transaction_id
    from gl_items as g
    inner join bank as b
        on
            g.bank_account_id = b.bank_account_id and g.reference = b.bank_reference
            and g.amount = b.amount
    where g.journal_id not in (select journal_id from r1)
        and b.bank_transaction_id not in (select bank_transaction_id from r1)
),

r2 as (
    select journal_id, bank_account_id, bank_transaction_id, 'EXACT_REFERENCE' as match_rule
    from r2_candidates
    qualify row_number() over (partition by journal_id, bank_account_id order by bank_transaction_id) = 1
        and row_number() over (partition by bank_transaction_id order by journal_id) = 1
),

matched_12 as (
    select * from r1
    union all
    select * from r2
),

r3_candidates as (
    select
        g.journal_id,
        g.bank_account_id,
        b.bank_transaction_id,
        count(*) over (partition by g.journal_id, g.bank_account_id) as gl_candidates,
        count(*) over (partition by b.bank_transaction_id) as bank_candidates
    from gl_items as g
    inner join bank as b
        on
            g.bank_account_id = b.bank_account_id and g.amount = b.amount
            and b.value_date between {{ add_days('g.posting_date', -tol) }} and {{ add_days('g.posting_date', tol) }}
    where not exists (select 1 from matched_12 as m where m.journal_id = g.journal_id and m.bank_account_id = g.bank_account_id)
        and not exists (select 1 from matched_12 as m where m.bank_transaction_id = b.bank_transaction_id)
),

r3 as (
    select journal_id, bank_account_id, bank_transaction_id, 'AMOUNT_DATE' as match_rule
    from r3_candidates
    where gl_candidates = 1 and bank_candidates = 1
),

matches as (
    select * from matched_12
    union all
    select * from r3
),

ambiguous_gl as (
    select distinct journal_id, bank_account_id from r3_candidates where gl_candidates > 1 or bank_candidates > 1
),

ambiguous_bank as (
    select distinct bank_transaction_id from r3_candidates where gl_candidates > 1 or bank_candidates > 1
),

latest_statement as (
    select bank_account_id, max(value_date) as last_value_date from bank group by 1
),

ledger_horizon as (
    select max(posting_date) as last_posting_date from {{ ref('fact_general_ledger') }}
),

duplicate_bank as (
    select b.bank_transaction_id
    from bank as b
    inner join bank as o
        on
            b.bank_account_id = o.bank_account_id and b.amount = o.amount and b.value_date = o.value_date
            and b.bank_transaction_id > o.bank_transaction_id
            and coalesce(b.bank_reference, '') = coalesce(o.bank_reference, '')
)

select
    {{ surrogate_key(['g.journal_id', 'g.bank_account_id']) }} as reconciliation_item_id,
    'LEDGER' as item_side,
    g.entity_id,
    g.bank_account_id,
    g.journal_id,
    m.bank_transaction_id,
    g.posting_date as item_date,
    {{ fiscal_period('g.posting_date') }} as fiscal_period,
    g.reference,
    g.amount,
    case
        when m.journal_id is not null then 'MATCHED'
        when a.journal_id is not null then 'AMBIGUOUS_REVIEW'
        when g.posting_date > {{ add_days('ls.last_value_date', -tol) }} then 'OUTSTANDING_IN_TRANSIT'
        else 'UNMATCHED_LEDGER'
    end as match_status,
    m.match_rule,
    case
        when m.journal_id is not null or g.posting_date > {{ add_days('ls.last_value_date', -tol) }} then 'INFO'
        when a.journal_id is not null then 'WARNING'
        else 'CRITICAL'
    end as severity
from gl_items as g
left join matches as m on g.journal_id = m.journal_id and g.bank_account_id = m.bank_account_id
left join ambiguous_gl as a on g.journal_id = a.journal_id and g.bank_account_id = a.bank_account_id and m.journal_id is null
left join latest_statement as ls on g.bank_account_id = ls.bank_account_id

union all

select
    {{ surrogate_key(['b.bank_transaction_id']) }},
    'BANK',
    b.entity_id,
    b.bank_account_id,
    m.journal_id,
    b.bank_transaction_id,
    b.value_date,
    b.fiscal_period,
    b.bank_reference,
    b.amount,
    case
        when m.bank_transaction_id is not null then 'MATCHED'
        when d.bank_transaction_id is not null then 'POSSIBLE_DUPLICATE'
        when a.bank_transaction_id is not null then 'AMBIGUOUS_REVIEW'
        when b.value_date > {{ add_days('(select last_posting_date from ledger_horizon)', -tol) }}
            then 'OUTSTANDING_NOT_YET_BOOKED'
        else 'UNMATCHED_BANK'
    end,
    m.match_rule,
    case
        when m.bank_transaction_id is not null then 'INFO'
        when d.bank_transaction_id is not null then 'CRITICAL'
        when a.bank_transaction_id is not null then 'WARNING'
        when b.value_date > {{ add_days('(select last_posting_date from ledger_horizon)', -tol) }} then 'INFO'
        else 'CRITICAL'
    end
from bank as b
left join matches as m on b.bank_transaction_id = m.bank_transaction_id
left join duplicate_bank as d on b.bank_transaction_id = d.bank_transaction_id
left join ambiguous_bank as a on b.bank_transaction_id = a.bank_transaction_id
