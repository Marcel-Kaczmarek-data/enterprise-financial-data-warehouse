-- {{ config(severity='error', tags=['critical']) }}
-- EUR-functional entities need no translation, so their currency translation adjustment must be 0.
select t.entity_id, t.fiscal_period, t.closing_balance_reporting
from {{ ref('int_translated_trial_balance') }} as t
inner join {{ ref('dim_legal_entity') }} as e on t.entity_id = e.entity_id
where t.group_account_code = '3200' and e.functional_currency = 'EUR' and abs(t.closing_balance_reporting) > 0.005
