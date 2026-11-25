-- Group chart of accounts with a flattened hierarchy (recursive CTE) for statement roll-ups.
-- Grain: one group account (headers and posting accounts).
with recursive coa as (
    select * from {{ ref('group_chart_of_accounts') }}
),

paths as (
    select
        group_account_code,
        group_account_code as level_1_code,
        cast(null as varchar) as level_2_code,
        cast(null as varchar) as level_3_code,
        1 as depth
    from coa
    where parent_group_account_code is null or parent_group_account_code = ''

    union all

    select
        c.group_account_code,
        p.level_1_code,
        case when p.depth = 1 then c.group_account_code else p.level_2_code end,
        case when p.depth = 2 then c.group_account_code else p.level_3_code end,
        p.depth + 1
    from coa as c
    inner join paths as p on c.parent_group_account_code = p.group_account_code
)

select
    {{ surrogate_key(['c.group_account_code']) }} as account_key,
    c.group_account_code,
    c.group_account_name,
    nullif(c.parent_group_account_code, '') as parent_group_account_code,
    c.hierarchy_level,
    c.account_type,
    c.account_category,
    c.statement,
    nullif(c.statement_line, '') as statement_line,
    c.normal_balance,
    c.translation_method,
    c.is_posting_account,
    p.level_1_code,
    l1.group_account_name as level_1_name,
    p.level_2_code,
    l2.group_account_name as level_2_name,
    p.level_3_code,
    l3.group_account_name as level_3_name,
    c.group_account_code in ('1190', '3200', '8400') as is_consolidation_only,
    case when c.statement = 'BALANCE_SHEET' then 'SEMI_ADDITIVE_BALANCE' else 'ADDITIVE_FLOW' end as measure_additivity
from coa as c
inner join paths as p on c.group_account_code = p.group_account_code
left join coa as l1 on p.level_1_code = l1.group_account_code
left join coa as l2 on p.level_2_code = l2.group_account_code
left join coa as l3 on p.level_3_code = l3.group_account_code
