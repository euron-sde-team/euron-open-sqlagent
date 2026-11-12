# One private bucket for everything too large to keep in Postgres:
#
#   projects/<id>/connections/<id>/<hex>.sqlite  uploaded SQLite databases; kept for as long
#                                                as the connection exists, never expired here
#   projects/<id>/results/<execution id>.json    query result snapshots (result pages and CSV
#                                                downloads are read from them); deleted by the
#                                                scheduler's retention after RETENTION_DAYS
#                                                (default 90)
#
# Retention of result snapshots is the app's job, not a lifecycle rule: S3 lifecycle
# filters match a key prefix, and the project id sits in front of `results/`, so a rule
# could not tell a snapshot from an uploaded database. Nothing under projects/ expires.
#
# Versioning is on: an overwritten or deleted object stays recoverable for
# noncurrent_retention_days (so a snapshot the scheduler deleted is gone for good after
# that), which protects uploaded databases from an accidental delete. Only the api, the
# worker, the scheduler and migrate may read the bucket.
resource "aws_s3_bucket" "objects" {
  #checkov:skip=CKV_AWS_144:Cross-region replication doubles where customer data lives; versioning and backups cover recovery (docs/guides/operations.md).
  #checkov:skip=CKV_AWS_18:Access logging targets a separate log bucket an operator chooses; CloudTrail data events cover object access (docs/guides/operations.md).
  #checkov:skip=CKV2_AWS_62:No consumer for S3 event notifications.
  bucket        = "${var.name_prefix}-objects"
  force_destroy = var.force_destroy
}

resource "aws_s3_bucket_versioning" "objects" {
  bucket = aws_s3_bucket.objects.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "objects" {
  bucket                  = aws_s3_bucket.objects.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "objects" {
  bucket = aws_s3_bucket.objects.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "objects" {
  bucket = aws_s3_bucket.objects.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.kms_key_arn != null ? "aws:kms" : "AES256"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = var.kms_key_arn != null
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "objects" {
  bucket     = aws_s3_bucket.objects.id
  depends_on = [aws_s3_bucket_versioning.objects]

  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  # Replaced or deleted versions stay recoverable for a while, then go.
  rule {
    id     = "expire-noncurrent"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_retention_days
    }
  }
}

# Only needed when a browser fetches objects with JavaScript. The app serves result pages
# and CSV downloads through the api, so the default is no CORS at all.
resource "aws_s3_bucket_cors_configuration" "objects" {
  count  = length(var.cors_origins) > 0 ? 1 : 0
  bucket = aws_s3_bucket.objects.id
  cors_rule {
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = var.cors_origins
    allowed_headers = ["*"]
    expose_headers  = ["Content-Disposition", "Content-Length", "ETag"]
    max_age_seconds = 3600
  }
}

data "aws_iam_policy_document" "objects" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.objects.arn, "${aws_s3_bucket.objects.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "objects" {
  count      = var.enforce_tls ? 1 : 0
  bucket     = aws_s3_bucket.objects.id
  policy     = data.aws_iam_policy_document.objects.json
  depends_on = [aws_s3_bucket_public_access_block.objects]
}
