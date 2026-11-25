# Development environment. NOTHING here is applied automatically:
#   terraform init && terraform plan -var-file=dev.tfvars   (review the plan)
#   terraform apply -var-file=dev.tfvars                    (explicit human approval only)
#   terraform destroy -var-file=dev.tfvars                  (cleanup)

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
    snowflake = {
      source  = "snowflakedb/snowflake"
      version = "~> 1.0"
    }
  }
  # Remote state (recommended for teams): configure an S3 backend with DynamoDB locking.
  # backend "s3" {}
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = local.tags
  }
}

# Credentials come from the environment (SNOWFLAKE_* variables, key-pair auth); never from files.
provider "snowflake" {}

locals {
  tags = {
    project     = "enterprise-financial-data-warehouse"
    environment = "dev"
    owner       = "finance-data-engineering"
    cost_center = "CC-DATA"
  }
}

module "data_lake" {
  source        = "../../modules/aws_data_lake"
  name_prefix   = var.name_prefix
  environment   = "dev"
  force_destroy = true
  tags          = local.tags
}

module "iam" {
  source                  = "../../modules/aws_iam"
  name_prefix             = var.name_prefix
  landing_bucket_arn      = module.data_lake.bucket_arns["landing"]
  quarantine_bucket_arn   = module.data_lake.bucket_arns["quarantine"]
  pipeline_principal_arns = var.pipeline_principal_arns
  snowflake_iam_user_arn  = var.snowflake_iam_user_arn
  snowflake_external_id   = var.snowflake_external_id
  tags                    = local.tags
}

module "snowflake" {
  source                  = "../../modules/snowflake_platform"
  environment             = "dev"
  database_name           = "FINANCE_DW_DEV"
  database_retention_days = 1
  monthly_credit_quota    = 20
}
