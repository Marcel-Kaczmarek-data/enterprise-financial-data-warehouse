variable "name_prefix" {
  description = "Globally unique bucket name prefix, e.g. acme-fdw-dev"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, prod)"
  type        = string
}

variable "kms_key_arn" {
  description = "Optional customer-managed KMS key; null uses SSE-S3 (AES256)"
  type        = string
  default     = null
}

variable "force_destroy" {
  description = "Allow terraform destroy to delete non-empty buckets (dev only)"
  type        = bool
  default     = false
}

variable "landing_ia_after_days" {
  description = "Days before landing objects move to STANDARD_IA"
  type        = number
  default     = 30
}

variable "retention_days" {
  description = "Retention of archived financial records in days"
  type        = number
  default     = 3650
}

variable "tags" {
  description = "Tags applied to every resource"
  type        = map(string)
  default     = {}
}
