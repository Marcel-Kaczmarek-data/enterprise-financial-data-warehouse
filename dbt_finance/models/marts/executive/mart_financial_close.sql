-- Month-end close monitor: period status, close-task completion and validations per entity/period.
-- Grain: entity x fiscal_period. Close tasks (each 1 = done):
--   journals balanced, trial balance balanced, AR reconciled, AP reconciled, bank exceptions cleared,
--   depreciation posted, accruals posted, FX revaluation posted (if foreign-currency cash), IC matched.
with periods as (
    select * from {{ ref('stg_erp__accounting_periods') }}
),

gl as (
    select
        entity_id,
        fiscal_period,
        count(distinct journal_id) as journals_posted,
        count(distinct case when journal_type = 'DEPRECIATION' then journal_id end) as depreciation_journals,
        count(distinct case when journal_type = 'ACCRUAL' then journal_id end) as accrual_journals,
        count(distinct case when journal_type = 'FX_REVALUATION' then journal_id end) as revaluation_journals,
        count(distinct case when journal_type in ('ADJUSTMENT', 'REVERSAL') then journal_id end) as manual_adjustments,
        sum(signed_amount_functional) as ledger_imbalance
    from {{ ref('fact_general_ledger') }}
    group by 1, 2
),

drafts as (
    select entity_id, fiscal_period, count(*) as draft_journals
    from {{ ref('stg_erp__journal_headers') }}
    where posting_status <> 'POSTED'
    group by 1, 2
),

recon as (
    select
        entity_id,
        fiscal_period,
        max(case when ledger = 'ACCOUNTS_RECEIVABLE' then difference end) as ar_difference,
        max(case when ledger = 'ACCOUNTS_PAYABLE' then difference end) as ap_difference
    from {{ ref('int_subledger_reconciliation') }}
    group by 1, 2
),

bank as (
    select entity_id, fiscal_period, count(*) as bank_exceptions
    from {{ ref('int_bank_transaction_matching') }}
    where severity = 'CRITICAL'
    group by 1, 2
),

ic as (
    select side_a_entity as entity_id, fiscal_period, count(*) as ic_mismatches
    from {{ ref('mart_intercompany_reconciliation') }}
    where reconciliation_status <> 'MATCHED'
    group by 1, 2
),

fx_accounts as (
    select b.entity_id, count(*) as foreign_currency_accounts
    from {{ ref('stg_erp__bank_accounts') }} as b
    inner join {{ ref('dim_legal_entity') }} as e on b.entity_id = e.entity_id
    where b.currency <> e.functional_currency
    group by 1
),

approvals as (
    select entity_id, fiscal_period, max(changed_at) as closed_at, max(changed_by) as approved_by
    from {{ ref('stg_erp__period_status_changes') }}
    where to_status = 'CLOSED'
    group by 1, 2
),

tasks as (
    select
        p.entity_id,
        p.fiscal_period,
        p.period_status,
        p.status_changed_at,
        coalesce(g.journals_posted, 0) as journals_posted,
        coalesce(d.draft_journals, 0) as draft_journals,
        coalesce(g.manual_adjustments, 0) as manual_adjustments,
        case when coalesce(g.ledger_imbalance, 0) = 0 then 1 else 0 end as task_journals_balanced,
        case when coalesce(g.ledger_imbalance, 0) = 0 then 1 else 0 end as task_trial_balance,
        case when abs(coalesce(r.ar_difference, 0)) <= {{ var('reconciliation_tolerance') }} then 1 else 0 end as task_ar_reconciled,
        case when abs(coalesce(r.ap_difference, 0)) <= {{ var('reconciliation_tolerance') }} then 1 else 0 end as task_ap_reconciled,
        case when coalesce(b.bank_exceptions, 0) = 0 then 1 else 0 end as task_bank_reconciled,
        case when coalesce(g.depreciation_journals, 0) > 0 then 1 else 0 end as task_depreciation_posted,
        case when coalesce(g.accrual_journals, 0) > 0 then 1 else 0 end as task_accruals_posted,
        case when coalesce(fa.foreign_currency_accounts, 0) = 0 or coalesce(g.revaluation_journals, 0) > 0 then 1 else 0 end
            as task_fx_revaluation_posted,
        case when coalesce(ic.ic_mismatches, 0) = 0 then 1 else 0 end as task_intercompany_matched,
        r.ar_difference,
        r.ap_difference,
        coalesce(b.bank_exceptions, 0) as bank_exceptions,
        coalesce(ic.ic_mismatches, 0) as ic_mismatches,
        a.closed_at,
        a.approved_by
    from periods as p
    left join gl as g on p.entity_id = g.entity_id and p.fiscal_period = g.fiscal_period
    left join drafts as d on p.entity_id = d.entity_id and p.fiscal_period = d.fiscal_period
    left join recon as r on p.entity_id = r.entity_id and p.fiscal_period = r.fiscal_period
    left join bank as b on p.entity_id = b.entity_id and p.fiscal_period = b.fiscal_period
    left join ic on p.entity_id = ic.entity_id and p.fiscal_period = ic.fiscal_period
    left join fx_accounts as fa on p.entity_id = fa.entity_id
    left join approvals as a on p.entity_id = a.entity_id and p.fiscal_period = a.fiscal_period
    where p.fiscal_period <= (select max(fiscal_period) from {{ ref('fact_general_ledger') }})
)

select
    t.*,
    task_journals_balanced + task_trial_balance + task_ar_reconciled + task_ap_reconciled + task_bank_reconciled
        + task_depreciation_posted + task_accruals_posted + task_fx_revaluation_posted + task_intercompany_matched
        as tasks_completed,
    9 as tasks_total,
    cast(task_journals_balanced + task_trial_balance + task_ar_reconciled + task_ap_reconciled + task_bank_reconciled
        + task_depreciation_posted + task_accruals_posted + task_fx_revaluation_posted + task_intercompany_matched
        as decimal(9, 4)) / 9 as close_completion_rate,
    task_journals_balanced = 1 and task_trial_balance = 1 and task_ar_reconciled = 1 and task_ap_reconciled = 1
        as critical_checks_passed,
    {{ audit_columns() }}
from tasks as t
