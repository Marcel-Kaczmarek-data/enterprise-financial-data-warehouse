-- Intercompany reconciliation per counterparty pair and period (EUR).
-- Grain: elimination_type x seller/parent x buyer/child x fiscal_period.
-- Status MATCHED when the residual is within the tolerance (percent of the larger side).
with elim as (
    select * from {{ ref('int_intercompany_eliminations') }}
),

pairs as (
    select
        elimination_id,
        elimination_type,
        fiscal_period,
        max(case when group_account_code in ('4500', '1150', '1700') then entity_id end) as side_a_entity,
        max(case when group_account_code in ('6650', '2050', '3000') then entity_id end) as side_b_entity,
        -sum(case when group_account_code in ('4500', '1150', '1700') then amount_reporting else 0 end) as side_a_amount,
        -sum(case when group_account_code in ('6650', '2050', '3000') then amount_reporting else 0 end) as side_b_amount,
        sum(case when group_account_code in ('8400', '1190', '3100') then amount_reporting else 0 end) as elimination_difference
    from elim
    group by 1, 2, 3
)

select
    p.*,
    greatest(abs(p.side_a_amount), abs(p.side_b_amount)) as larger_side,
    {{ safe_divide('abs(p.elimination_difference) * 100', 'greatest(abs(p.side_a_amount), abs(p.side_b_amount))') }}
        as difference_pct,
    case
        when abs(p.elimination_difference) <= greatest(abs(p.side_a_amount), abs(p.side_b_amount))
            * {{ var('intercompany_tolerance_pct') }} / 100 then 'MATCHED'
        when p.side_a_amount = 0 or p.side_b_amount = 0 then 'MISSING_COUNTERPART'
        else 'MISMATCH'
    end as reconciliation_status,
    '{{ var("group_reporting_currency") }}' as reporting_currency,
    {{ audit_columns() }}
from pairs as p
