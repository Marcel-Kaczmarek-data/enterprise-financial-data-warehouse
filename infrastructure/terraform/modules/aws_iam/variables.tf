variable "name_prefix" {
  description = "Name prefix for IAM resources"
  type        = string
}

variable "landing_bucket_arn" {
  description = "ARN of the landing bucket"
  type        = string
}

variable "quarantine_bucket_arn" {
  description = "ARN of the quarantine bucket"
  type        = string
}

variable "pipeline_principal_arns" {
  description = "Principals allowed to assume the pipeline role (e.g. the Airflow worker role)"
  type        = list(string)
}

variable "snowflake_iam_user_arn" {
  description = "STORAGE_AWS_IAM_USER_ARN from DESC INTEGRATION (Snowflake)"
  type        = string
}

variable "snowflake_external_id" {
  description = "STORAGE_AWS_EXTERNAL_ID from DESC INTEGRATION (Snowflake)"
  type        = string
  sensitive   = true
}

variable "tags" {
  description = "Tags applied to every resource"
  type        = map(string)
  default     = {}
}
