-- House bank accounts. Account numbers are masked at source; see docs/security.md for the
-- Snowflake masking policy applied to account_number_masked in the cloud environment.
select
    {{ surrogate_key(['b.bank_account_id']) }} as bank_account_key,
    b.bank_account_id,
    b.entity_id,
    b.bank_name,
    b.account_number_masked,
    b.currency,
    b.account_purpose,
    b.gl_account_id,
    a.local_account_code as gl_account_code,
    b.opened_date
from {{ ref('stg_erp__bank_accounts') }} as b
left join {{ ref('int_account_mapping') }} as a on b.gl_account_id = a.account_id
