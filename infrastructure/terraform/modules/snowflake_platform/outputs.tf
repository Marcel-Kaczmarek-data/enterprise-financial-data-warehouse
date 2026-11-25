output "database_name" {
  description = "Finance database"
  value       = snowflake_database.finance.name
}

output "warehouses" {
  description = "Workload warehouse names"
  value       = [for w in snowflake_warehouse.workloads : w.name]
}
