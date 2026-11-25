variable "environment" {
  description = "Environment name (dev, prod)"
  type        = string
}

variable "database_name" {
  description = "Snowflake database name"
  type        = string
}

variable "database_retention_days" {
  description = "Default Time Travel retention for the database"
  type        = number
  default     = 1
}

variable "monthly_credit_quota" {
  description = "Resource monitor credit quota per month"
  type        = number
  default     = 50
}

variable "warehouse_sizes" {
  description = "Warehouse sizes per workload (start small; scale with benchmark evidence)"
  type = object({
    ingest    = string
    transform = string
    bi        = string
  })
  default = { ingest = "XSMALL", transform = "XSMALL", bi = "XSMALL" }
}
