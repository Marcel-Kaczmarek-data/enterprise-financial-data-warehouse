-- Local (entity) posting account -> group account, group hierarchy and statement line.
-- Mappings are effective-dated; the latest valid mapping applies. Unmapped accounts keep a NULL
-- group_account_code, which the not_null test on this model reports as a critical failure.
with accounts as (
    select * from {{ ref('stg_erp__accounts') }}
),

mappings as (
    select *
    from {{ ref('stg_erp__account_mappings') }}
    qualify row_number() over (partition by account_id order by valid_from desc) = 1
),

group_coa as (
    select * from {{ ref('group_chart_of_accounts') }}
)

select
    a.account_id,
    a.entity_id,
    a.account_code as local_account_code,
    a.account_name as local_account_name,
    a.bank_account_id,
    m.mapping_id,
    m.mapping_version,
    g.group_account_code,
    g.group_account_name,
    g.parent_group_account_code,
    g.account_type,
    g.account_category,
    g.statement,
    g.statement_line,
    g.normal_balance,
    g.translation_method
from accounts as a
left join mappings as m on a.account_id = m.account_id
left join group_coa as g on m.group_account_code = g.group_account_code
