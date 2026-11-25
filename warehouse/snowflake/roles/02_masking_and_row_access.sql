-- =====================================================================================
-- Data governance policies: dynamic masking, row access, tags. Enterprise edition features.
-- STATUS: NOT executed against a real Snowflake account. The LOCAL DuckDB environment does NOT
-- enforce these policies; local "roles" are documentation only (see docs/security.md).
-- =====================================================================================
use role finance_admin;
use schema finance_dw.governance;

create tag if not exists data_classification allowed_values 'PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED';
create tag if not exists data_owner;

-- PII (customer contact, tax identifiers): only finance admin and auditors see clear text.
create masking policy if not exists mask_pii as (val string) returns string ->
    case when is_role_in_session('FINANCE_ADMIN') or is_role_in_session('AUDITOR') then val
         else regexp_replace(val, '.', '*', 4) end;

-- Bank account numbers: last four characters only, except treasury admins.
create masking policy if not exists mask_bank_account as (val string) returns string ->
    case when is_role_in_session('FINANCE_ADMIN') then val
         else '**** **** ' || right(val, 4) end;

-- Payroll amounts: CFO / finance admin only.
create masking policy if not exists mask_payroll_amount as (val number(19, 4)) returns number(19, 4) ->
    case when is_role_in_session('CFO') or is_role_in_session('FINANCE_ADMIN') then val else null end;

-- Entitlements for subsidiary- and department-based row filtering.
create table if not exists finance_dw.governance.entity_entitlements (
    role_name varchar, entity_id varchar, department_id varchar);  -- department_id null = all

create row access policy if not exists rap_entity_department as (p_entity varchar, p_department varchar)
    returns boolean ->
    is_role_in_session('FINANCE_ADMIN') or is_role_in_session('CFO') or is_role_in_session('AUDITOR')
    or is_role_in_session('FINANCE_CONTROLLER')
    or exists (
        select 1 from finance_dw.governance.entity_entitlements e
        where is_role_in_session(e.role_name) and e.entity_id = p_entity
          and (e.department_id is null or e.department_id = p_department));

-- Apply after dbt builds (idempotent ALTERs; executed by the post-deployment job):
-- alter table finance_dw.finance_staging.stg_crm__customers modify column contact_email
--     set masking policy finance_dw.governance.mask_pii;
-- alter table finance_dw.finance_core.dim_bank_account modify column account_number_masked
--     set masking policy finance_dw.governance.mask_bank_account;
-- alter table finance_dw.finance_core.fact_payroll modify column total_employment_cost
--     set masking policy finance_dw.governance.mask_payroll_amount;
-- alter table finance_dw.finance_marts.mart_department_performance
--     add row access policy finance_dw.governance.rap_entity_department on (entity_id, department_id);
-- alter table finance_dw.finance_core.fact_payroll set tag data_classification = 'RESTRICTED';

-- Secure view for department managers (definition hidden, row policy applies).
-- create secure view finance_dw.finance_marts.v_department_budget as
--     select * from finance_dw.finance_marts.mart_budget_vs_actual;
