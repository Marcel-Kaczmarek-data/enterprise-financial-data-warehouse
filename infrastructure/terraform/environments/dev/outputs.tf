output "buckets" {
  description = "Data lake buckets"
  value       = module.data_lake.bucket_names
}

output "snowflake_s3_role_arn" {
  description = "Set as STORAGE_AWS_ROLE_ARN of the storage integration"
  value       = module.iam.snowflake_role_arn
}

output "snowflake_database" {
  description = "Snowflake database"
  value       = module.snowflake.database_name
}
