# Finance data lake buckets: landing (+ manifests/audit/reconciliation prefixes), archive, quarantine.
# Encryption at rest (SSE-KMS optional), versioning, public access block, access logging and
# lifecycle policies. Creating these resources costs money only for stored data and requests.

locals {
  buckets = {
    landing    = "${var.name_prefix}-landing"
    archive    = "${var.name_prefix}-archive"
    quarantine = "${var.name_prefix}-quarantine"
    logs       = "${var.name_prefix}-access-logs"
  }
}

resource "aws_s3_bucket" "this" {
  for_each      = local.buckets
  bucket        = each.value
  force_destroy = var.force_destroy
  tags          = merge(var.tags, { data_zone = each.key })
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each                = aws_s3_bucket.this
  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = { for k, b in aws_s3_bucket.this : k => b if k != "logs" }
  bucket   = each.value.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.kms_key_arn == null ? "AES256" : "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = var.kms_key_arn != null
  }
}

resource "aws_s3_bucket_logging" "this" {
  for_each      = { for k, b in aws_s3_bucket.this : k => b if k != "logs" }
  bucket        = each.value.id
  target_bucket = aws_s3_bucket.this["logs"].id
  target_prefix = "${each.key}/"
}

resource "aws_s3_bucket_lifecycle_configuration" "landing" {
  bucket = aws_s3_bucket.this["landing"].id

  rule {
    id     = "landing-to-infrequent-access"
    status = "Enabled"
    filter {
      prefix = "landing/"
    }
    transition {
      days          = var.landing_ia_after_days
      storage_class = "STANDARD_IA"
    }
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }

  rule {
    id     = "raw-originals-to-glacier"
    status = "Enabled"
    filter {
      prefix = "raw/"
    }
    transition {
      days          = 90
      storage_class = "GLACIER_IR"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "archive" {
  bucket = aws_s3_bucket.this["archive"].id
  rule {
    id     = "financial-record-retention"
    status = "Enabled"
    filter {}
    transition {
      days          = 30
      storage_class = "DEEP_ARCHIVE"
    }
    # Statutory retention for accounting records (illustrative: 10 years); never expire earlier.
    expiration {
      days = var.retention_days
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "quarantine" {
  bucket = aws_s3_bucket.this["quarantine"].id
  rule {
    id     = "quarantine-expiry"
    status = "Enabled"
    filter {}
    expiration {
      days = 180
    }
  }
}

resource "aws_cloudwatch_log_group" "pipeline" {
  name              = "/fdw/${var.environment}/pipeline"
  retention_in_days = 90
  tags              = var.tags
}
