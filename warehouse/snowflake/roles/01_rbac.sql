-- =====================================================================================
-- Role-based access control (least privilege). Run as SECURITYADMIN / USERADMIN.
-- STATUS: NOT executed against a real Snowflake account; see docs/security.md for the matrix.
-- Pattern: access roles (schema privileges) are granted to functional roles; users get
-- functional roles only. Future grants keep new dbt objects covered.
-- =====================================================================================
use role securityadmin;

-- Functional roles
create role if not exists finance_admin;
create role if not exists data_engineer;
create role if not exists analytics_engineer;
create role if not exists finance_controller;
create role if not exists cfo;
create role if not exists department_manager;
create role if not exists auditor;
create role if not exists bi_service;
create role if not exists read_only;

-- Role hierarchy (privileges inherit upward)
grant role read_only to role department_manager;
grant role read_only to role auditor;
grant role department_manager to role finance_controller;
grant role finance_controller to role cfo;
grant role read_only to role bi_service;
grant role analytics_engineer to role data_engineer;
grant role data_engineer to role finance_admin;
grant role cfo to role finance_admin;
grant role finance_admin to role sysadmin;

-- Warehouses
grant usage on warehouse finance_ingest_wh to role data_engineer;
grant usage on warehouse finance_transform_wh to role analytics_engineer;
grant usage on warehouse finance_dev_wh to role analytics_engineer;
grant usage on warehouse finance_bi_wh to role read_only;
grant usage on warehouse finance_admin_wh to role finance_admin;

grant usage on database finance_dw to role read_only;
grant usage on database finance_dw to role analytics_engineer;

-- Engineering: raw is written by ingestion only; dbt owns staging -> marts.
grant usage, create table, create stage, create file format on schema finance_dw.finance_raw to role data_engineer;
grant select, insert on future tables in schema finance_dw.finance_raw to role data_engineer;
grant select on future tables in schema finance_dw.finance_raw to role analytics_engineer;
grant usage on schema finance_dw.finance_raw to role analytics_engineer;
grant usage, create table, create view on schema finance_dw.finance_staging to role analytics_engineer;
grant usage, create table, create view on schema finance_dw.finance_intermediate to role analytics_engineer;
grant usage, create table, create view on schema finance_dw.finance_core to role analytics_engineer;
grant usage, create table, create view on schema finance_dw.finance_marts to role analytics_engineer;
grant usage, create table on schema finance_dw.finance_audit to role analytics_engineer;
grant usage, create table on schema finance_dw.finance_snapshots to role analytics_engineer;

-- Consumers: marts for everyone with read access; core for controllers; audit for auditors.
grant usage on schema finance_dw.finance_marts to role read_only;
grant select on future tables in schema finance_dw.finance_marts to role read_only;
grant select on future views in schema finance_dw.finance_marts to role read_only;
grant usage on schema finance_dw.finance_core to role finance_controller;
grant select on future tables in schema finance_dw.finance_core to role finance_controller;
grant usage on schema finance_dw.finance_audit to role auditor;
grant select on future tables in schema finance_dw.finance_audit to role auditor;
grant usage on schema finance_dw.finance_core to role auditor;
grant select on future tables in schema finance_dw.finance_core to role auditor;

-- Restricted payroll: fact_payroll / dim_employee are readable by CFO and finance admin only.
-- Future grants cover the whole schema, so the restriction is applied per table after each dbt
-- deployment (post-deployment job), and masking on salary columns is a second line of defence.
--   revoke select on table finance_dw.finance_core.fact_payroll from role finance_controller;
--   revoke select on table finance_dw.finance_core.fact_payroll from role auditor;
--   grant select on table finance_dw.finance_core.fact_payroll to role cfo;

-- Service user for Power BI (key-pair auth, no password; network policy restricts source IPs)
-- create user svc_powerbi type = service default_role = bi_service default_warehouse = finance_bi_wh
--     rsa_public_key = '<public key>';
-- grant role bi_service to user svc_powerbi;
