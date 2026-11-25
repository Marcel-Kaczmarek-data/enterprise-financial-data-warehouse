# Snowflake platform objects: database, layer schemas, workload warehouses, resource monitor and
# the functional role hierarchy. Warehouses are created SUSPENDED at XSMALL (no idle cost).

locals {
  schemas = {
    FINANCE_RAW          = 1
    FINANCE_STAGING      = 1
    FINANCE_INTERMEDIATE = 1
    FINANCE_CORE         = 30
    FINANCE_MARTS        = 30
    FINANCE_AUDIT        = 90
    FINANCE_MONITORING   = 1
    FINANCE_SNAPSHOTS    = 30
    GOVERNANCE           = 1
  }
  warehouses = {
    FINANCE_INGEST_WH    = { size = var.warehouse_sizes.ingest, suspend = 60 }
    FINANCE_TRANSFORM_WH = { size = var.warehouse_sizes.transform, suspend = 60 }
    FINANCE_BI_WH        = { size = var.warehouse_sizes.bi, suspend = 300 }
    FINANCE_DEV_WH       = { size = "XSMALL", suspend = 60 }
  }
  roles = ["FINANCE_ADMIN", "DATA_ENGINEER", "ANALYTICS_ENGINEER", "FINANCE_CONTROLLER", "CFO",
  "DEPARTMENT_MANAGER", "AUDITOR", "BI_SERVICE", "READ_ONLY"]
  # child => parent (privileges of the child are inherited by the parent)
  hierarchy = {
    READ_ONLY_TO_DEPARTMENT_MANAGER     = ["READ_ONLY", "DEPARTMENT_MANAGER"]
    READ_ONLY_TO_AUDITOR                = ["READ_ONLY", "AUDITOR"]
    READ_ONLY_TO_BI_SERVICE             = ["READ_ONLY", "BI_SERVICE"]
    DEPARTMENT_MANAGER_TO_CONTROLLER    = ["DEPARTMENT_MANAGER", "FINANCE_CONTROLLER"]
    CONTROLLER_TO_CFO                   = ["FINANCE_CONTROLLER", "CFO"]
    ANALYTICS_ENGINEER_TO_DATA_ENGINEER = ["ANALYTICS_ENGINEER", "DATA_ENGINEER"]
    DATA_ENGINEER_TO_FINANCE_ADMIN      = ["DATA_ENGINEER", "FINANCE_ADMIN"]
    CFO_TO_FINANCE_ADMIN                = ["CFO", "FINANCE_ADMIN"]
  }
}

resource "snowflake_database" "finance" {
  name                        = var.database_name
  data_retention_time_in_days = var.database_retention_days
  comment                     = "Enterprise financial data warehouse (${var.environment})"
}

resource "snowflake_schema" "layers" {
  for_each                    = local.schemas
  database                    = snowflake_database.finance.name
  name                        = each.key
  data_retention_time_in_days = each.value
}

resource "snowflake_resource_monitor" "finance" {
  name                      = "FINANCE_${upper(var.environment)}_MONITOR"
  credit_quota              = var.monthly_credit_quota
  frequency                 = "MONTHLY"
  start_timestamp           = "IMMEDIATELY"
  notify_triggers           = [75]
  suspend_trigger           = 90
  suspend_immediate_trigger = 100
}

resource "snowflake_warehouse" "workloads" {
  for_each            = local.warehouses
  name                = each.key
  warehouse_size      = each.value.size
  auto_suspend        = each.value.suspend
  auto_resume         = "true"
  initially_suspended = true
  resource_monitor    = snowflake_resource_monitor.finance.name
}

resource "snowflake_account_role" "functional" {
  for_each = toset(local.roles)
  name     = each.value
}

resource "snowflake_grant_account_role" "hierarchy" {
  for_each         = local.hierarchy
  role_name        = snowflake_account_role.functional[each.value[0]].name
  parent_role_name = snowflake_account_role.functional[each.value[1]].name
}

resource "snowflake_grant_privileges_to_account_role" "warehouse_usage" {
  for_each = {
    FINANCE_INGEST_WH    = "DATA_ENGINEER"
    FINANCE_TRANSFORM_WH = "ANALYTICS_ENGINEER"
    FINANCE_DEV_WH       = "ANALYTICS_ENGINEER"
    FINANCE_BI_WH        = "READ_ONLY"
  }
  account_role_name = snowflake_account_role.functional[each.value].name
  privileges        = ["USAGE"]
  on_account_object {
    object_type = "WAREHOUSE"
    object_name = snowflake_warehouse.workloads[each.key].name
  }
}

resource "snowflake_grant_privileges_to_account_role" "database_usage" {
  for_each          = toset(["READ_ONLY", "ANALYTICS_ENGINEER"])
  account_role_name = snowflake_account_role.functional[each.value].name
  privileges        = ["USAGE"]
  on_account_object {
    object_type = "DATABASE"
    object_name = snowflake_database.finance.name
  }
}

resource "snowflake_grant_privileges_to_account_role" "transform_schemas" {
  for_each          = toset(["FINANCE_STAGING", "FINANCE_INTERMEDIATE", "FINANCE_CORE", "FINANCE_MARTS", "FINANCE_AUDIT", "FINANCE_SNAPSHOTS"])
  account_role_name = snowflake_account_role.functional["ANALYTICS_ENGINEER"].name
  privileges        = ["USAGE", "CREATE TABLE", "CREATE VIEW"]
  on_schema {
    schema_name = "\"${snowflake_database.finance.name}\".\"${snowflake_schema.layers[each.value].name}\""
  }
}

resource "snowflake_grant_privileges_to_account_role" "marts_read" {
  account_role_name = snowflake_account_role.functional["READ_ONLY"].name
  privileges        = ["SELECT"]
  on_schema_object {
    future {
      object_type_plural = "TABLES"
      in_schema          = "\"${snowflake_database.finance.name}\".\"${snowflake_schema.layers["FINANCE_MARTS"].name}\""
    }
  }
}
