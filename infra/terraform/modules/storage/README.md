# `storage` module

One private S3 bucket, `<name_prefix>-objects` (`OBJECTS_BUCKET`):

- `projects/<id>/connections/<id>/<hex>.sqlite`: uploaded SQLite databases, kept as long as the connection exists. Never expired by a lifecycle rule.
- `projects/<id>/results/<execution id>.json`: query result snapshots (result pages and CSV downloads are read from them), deleted by the scheduler's retention after `RETENTION_DAYS` (default 90). S3 lifecycle filters match a key prefix and the project id comes before `results/`, so retention is the app's job, not a lifecycle rule.
- Only the api, the worker, the scheduler and migrate may read or write the bucket.

Versioning is on, and replaced or deleted versions stay recoverable for `noncurrent_retention_days`. Incomplete multipart uploads are aborted after a day. Public access blocked, bucket-owner-enforced ownership, TLS-only bucket policy, SSE-KMS with the CMK (bucket key on). Applied in `local-floci` as `sqlagent-local-objects` with `enforce_tls = false` (the emulator speaks plain HTTP) and `force_destroy = true`.

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| `name_prefix` | Prefix for every resource name. The bucket is <name_prefix>-objects. | `string` | required |
| `kms_key_arn` | CMK for SSE-KMS. Null falls back to SSE-S3. | `string` | `null` |
| `enforce_tls` | Deny any request not made over TLS. Disable only for an emulator that speaks plain HTTP. | `bool` | `true` |
| `noncurrent_retention_days` | Days a replaced or deleted object version (an uploaded SQLite database, a result snapshot removed by retention) stays recoverable. | `number` | `30` |
| `cors_origins` | Browser origins allowed to GET objects with JavaScript (the app URL). Empty = no CORS configuration. | `list(string)` | `[]` |
| `force_destroy` | Allow `terraform destroy` to delete a non-empty bucket. Never in production. | `bool` | `false` |

## Outputs

| Name | Description |
|---|---|
| `bucket_name` | Objects bucket name (OBJECTS_BUCKET). |
| `bucket_arn` | Objects bucket ARN, for IAM policies. |
