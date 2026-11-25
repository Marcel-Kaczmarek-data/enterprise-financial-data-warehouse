output "bucket_names" {
  description = "Bucket names by data zone"
  value       = { for k, b in aws_s3_bucket.this : k => b.bucket }
}

output "bucket_arns" {
  description = "Bucket ARNs by data zone"
  value       = { for k, b in aws_s3_bucket.this : k => b.arn }
}

output "pipeline_log_group" {
  description = "CloudWatch log group for pipeline logs"
  value       = aws_cloudwatch_log_group.pipeline.name
}
