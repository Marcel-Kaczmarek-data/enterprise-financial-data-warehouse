output "pipeline_role_arn" {
  description = "Role assumed by the ingestion pipeline"
  value       = aws_iam_role.pipeline.arn
}

output "snowflake_role_arn" {
  description = "Role trusted by the Snowflake storage integration"
  value       = aws_iam_role.snowflake.arn
}
