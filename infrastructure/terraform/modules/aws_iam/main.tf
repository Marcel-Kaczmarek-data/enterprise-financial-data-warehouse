# Least-privilege IAM:
#  * pipeline writer: put objects under landing/manifests/audit/raw/quarantine prefixes, read back,
#    list the bucket - no delete (immutable landing zone; versioning keeps history).
#  * Snowflake reader: assumed by the Snowflake storage integration (external ID enforced),
#    read-only on landing/ and manifests/.

data "aws_iam_policy_document" "pipeline_writer" {
  statement {
    sid     = "WriteLandingZones"
    actions = ["s3:PutObject", "s3:GetObject"]
    resources = [for p in ["landing", "manifests", "audit", "raw", "reconciliation"] :
    "${var.landing_bucket_arn}/${p}/*"]
  }
  statement {
    sid       = "WriteQuarantine"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${var.quarantine_bucket_arn}/*"]
  }
  statement {
    sid       = "ListBuckets"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [var.landing_bucket_arn, var.quarantine_bucket_arn]
  }
}

resource "aws_iam_policy" "pipeline_writer" {
  name   = "${var.name_prefix}-pipeline-writer"
  policy = data.aws_iam_policy_document.pipeline_writer.json
  tags   = var.tags
}

data "aws_iam_policy_document" "pipeline_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = var.pipeline_principal_arns
    }
  }
}

resource "aws_iam_role" "pipeline" {
  name               = "${var.name_prefix}-pipeline"
  assume_role_policy = data.aws_iam_policy_document.pipeline_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "pipeline" {
  role       = aws_iam_role.pipeline.name
  policy_arn = aws_iam_policy.pipeline_writer.arn
}

data "aws_iam_policy_document" "snowflake_read" {
  statement {
    sid       = "ReadLanding"
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${var.landing_bucket_arn}/landing/*", "${var.landing_bucket_arn}/manifests/*"]
  }
  statement {
    sid       = "ListLanding"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [var.landing_bucket_arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["landing/*", "manifests/*"]
    }
  }
}

resource "aws_iam_policy" "snowflake_read" {
  name   = "${var.name_prefix}-snowflake-read"
  policy = data.aws_iam_policy_document.snowflake_read.json
  tags   = var.tags
}

data "aws_iam_policy_document" "snowflake_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = [var.snowflake_iam_user_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "sts:ExternalId"
      values   = [var.snowflake_external_id]
    }
  }
}

resource "aws_iam_role" "snowflake" {
  name               = "${var.name_prefix}-snowflake-s3-read"
  assume_role_policy = data.aws_iam_policy_document.snowflake_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "snowflake" {
  role       = aws_iam_role.snowflake.name
  policy_arn = aws_iam_policy.snowflake_read.arn
}
