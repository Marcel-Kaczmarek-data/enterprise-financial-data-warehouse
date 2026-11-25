-- Subledger vs general ledger control-account reconciliation at every month end (functional).
-- AR: open customer items (fact_receivables_snapshot) vs GL 1100 + 1150
-- AP: open supplier items (fact_payables_snapshot)    vs GL 2000 + 2050 (sign flipped)
-- Grain: ledger x entity x fiscal_period.
{% set tol = var('reconciliation_tolerance') %}

with gl as (
    select
        entity_id,
        fiscal_period,
        sum(case when group_account_code in ('1100', '1150') then closing_balance_functional else 0 end) as gl_ar,
        -sum(case when group_account_code in ('2000', '2050') then closing_balance_functional else 0 end) as gl_ap
    from {{ ref('fact_monthly_account_balances') }}
    where group_account_code in ('1100', '1150', '2000', '2050')
    group by 1, 2
),

ar as (
    select s.entity_id, s.fiscal_period, sum(s.outstanding_amount_functional) as sub_ar
    from {{ ref('fact_receivables_snapshot') }} as s
    inner join {{ ref('dim_fiscal_period') }} as p on s.snapshot_date = p.period_end
    group by 1, 2
),

ap as (
    select s.entity_id, s.fiscal_period, sum(s.outstanding_amount_functional) as sub_ap
    from {{ ref('fact_payables_snapshot') }} as s
    inner join {{ ref('dim_fiscal_period') }} as p on s.snapshot_date = p.period_end
    group by 1, 2
),

unioned as (
    select 'ACCOUNTS_RECEIVABLE' as ledger, g.entity_id, g.fiscal_period, g.gl_ar as gl_balance,
        coalesce(ar.sub_ar, 0) as subledger_balance
    from gl as g
    left join ar on g.entity_id = ar.entity_id and g.fiscal_period = ar.fiscal_period
    union all
    select 'ACCOUNTS_PAYABLE', g.entity_id, g.fiscal_period, g.gl_ap, coalesce(ap.sub_ap, 0)
    from gl as g
    left join ap on g.entity_id = ap.entity_id and g.fiscal_period = ap.fiscal_period
)

select
    u.*,
    e.functional_currency,
    u.gl_balance - u.subledger_balance as difference,
    case when abs(u.gl_balance - u.subledger_balance) <= {{ tol }} then 'RECONCILED' else 'DIFFERENCE' end
        as reconciliation_status
from unioned as u
left join {{ ref('dim_legal_entity') }} as e on u.entity_id = e.entity_id
