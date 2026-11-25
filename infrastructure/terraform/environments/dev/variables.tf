variable "aws_region" {
  description = "AWS region for the data lake"
  type        = string
  default     = "eu-central-1"
}

variable "name_prefix" {
  description = "Globally unique prefix for bucket and role names"
  type        = string
}

variable "pipeline_principal_arns" {
  description = "IAM principals allowed to assume the pipeline role"
  type        = list(string)
}

variable "snowflake_iam_user_arn" {
  description = "From DESC INTEGRATION finance_s3_integration"
  type        = string
}

variable "snowflake_external_id" {
  description = "From DESC INTEGRATION finance_s3_integration"
  type        = string
  sensitive   = true
}
