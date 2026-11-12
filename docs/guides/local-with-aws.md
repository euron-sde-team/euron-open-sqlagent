# Local stack against real AWS

`make up-aws` runs the same containers as `make up`, but the API, the question worker, the
scheduler and the migrations use a real KMS key and S3 bucket instead of Floci. Postgres,
Redis, Mailpit, the mock model provider, the demo databases and the web app stay local. Use
it to check the AWS code paths with your own account before a deployment.

## Set up

```bash
cd infra/terraform/envs/aws-dev && terraform apply -target=module.kms -target=module.storage   # or use your own key and bucket
cd -
cp deploy/compose/.env.aws.example deploy/compose/.env.aws    # fill in from terraform output
make up-aws
```

The two outputs you need are `objects_bucket` and `kms_key_alias` (`terraform output` in
`infra/terraform/envs/aws-dev`). The targeted apply still needs a filled-in
`terraform.tfvars` ([deploy-aws.md](deploy-aws.md#deploy)).

`deploy/compose/.env.aws` is git-ignored and holds only resource names:

| Variable | Example | Meaning |
| --- | --- | --- |
| `AWS_REGION` | `us-east-1` | Region of the key and the bucket |
| `AWS_PROFILE` | `default` | Optional: the AWS CLI profile to use |
| `OBJECTS_BUCKET` | `<objects_bucket output>` | Bucket for SQLite uploads and result snapshots |
| `KMS_KEY_ID` | `<kms_key_alias output>` | Key that seals connection passwords and provider keys |

## How it works

`make up-aws` runs `compose.yaml` with the `compose.aws.yaml` overlay instead of
`compose.floci.yaml`, so there is no emulator, no Terraform one-shot and no
`AWS_ENDPOINT_URL`. The overlay sets `SQLAGENT_CLOUD=aws`, `STORAGE=s3` and `KEY_MODE=kms`
on `migrate`, `api`, `worker` and `scheduler`, reads `.env.aws` into them, and mounts
`~/.aws` read-only at `/app/.aws` with `AWS_SDK_LOAD_CONFIG=1`. Credentials come from your
AWS CLI profile; nothing in the repository holds a static key. The containers run as user
10001, so the files under `~/.aws` must be readable by it.

The stack still runs with `ENVIRONMENT=development`, so the production guards stay off
(the app links to `http://localhost` and sends mail to Mailpit).

The identity behind your profile needs, on that key and bucket, at least `kms:Encrypt` and
`kms:Decrypt`, and `s3:PutObject`, `s3:GetObject` and `s3:DeleteObject`. The key policy the
`kms` module writes delegates to IAM in the account.

## What changes

| | `make up` | `make up-aws` |
| --- | --- | --- |
| SQLite uploads and result snapshots | S3 on Floci | Your S3 bucket, SSE-KMS |
| Connection passwords, provider API keys and headers | Sealed by Floci's KMS | Sealed by your KMS key, encryption context bound to the row |
| Postgres, Redis, the demo databases, the mock provider | Local containers | Local containers |
| Notice mail | Mailpit | Mailpit |
| Terraform | `local-floci` applied on every start | Nothing applied |

Everything else behaves exactly as in `make up`. `make demo` works the same way, and its
result snapshots then land in your bucket.

## Switching back

Sealed values are tied to the key that sealed them: connections and providers created under
`make up` (sealed by Floci's KMS) cannot be opened under `make up-aws`, and the reverse.
Result snapshots written to one bucket are not in the other either. Run `make down` between
the two (it deletes the local data of both), or re-enter connection passwords and provider
keys.

`make down` does not touch your AWS resources. Objects in the bucket are deleted by the
scheduler's retention after `RETENTION_DAYS`, or by `terraform destroy` of the targeted
modules when you are done.
