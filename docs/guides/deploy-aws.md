# Deploy to AWS

The Terraform in `infra/terraform/` builds a production deployment. This repository never
applies it to a real AWS account itself: the maintainers develop against the local
emulator, the `aws-dev` and `aws-prod` environments pass `terraform validate`, tflint and
checkov, and the full `aws-dev` environment is planned, applied, re-planned and destroyed
against a throwaway Floci (`make tf-aws-on-floci`). Applying it to a real account is your
step; read the plan before you apply.

## What it builds

| Module | Resources |
| --- | --- |
| `network` | VPC across two or three availability zones, public and private subnets, NAT (one shared or one per zone), an S3 gateway endpoint, optional interface endpoints (KMS, Secrets Manager and the other AWS APIs the tasks call), encrypted flow logs |
| `database` | RDS PostgreSQL 16 in private subnets for every SQLAgent table, including the question queue and the append-only audit log. Encrypted with the KMS key, TLS enforced, the generated master password stored only inside `DATABASE_URL` in Secrets Manager |
| `cache` | ElastiCache (Valkey by default) for rate limits, caches and the pub/sub wake-ups between the API and the workers. TLS and an AUTH token. Nothing in it is the only copy of anything |
| `storage` | The objects bucket: uploaded SQLite databases and query result snapshots. SSE-KMS, versioning, public access blocked, TLS only |
| `kms` | One customer-managed key with annual rotation. It seals connection passwords and model provider keys (encryption context `sqlagent:record`) and encrypts the bucket, RDS, ElastiCache, Secrets Manager and logs |
| `secrets` | Secrets Manager entries injected into the containers: `SESSION_SECRET` and `API_KEY_PEPPER`, and `DATABASE_URL` and `REDIS_URL` |
| `ecr` | Repositories for the `api` image (also the worker, the scheduler and the one-off tasks) and the `web` image. Immutable tags |
| `email` | An SES domain identity with DKIM for project notice mail, and a policy that lets the API (the only sender) send only as the configured address |
| `service` | ECS Fargate services for `api`, `worker`, `scheduler` and `web` behind one ALB with HTTPS and WAF, plus a `migrate` task definition for one-off commands. ARM64, read-only root filesystems, no public IPs |
| `observability` | CloudWatch log groups per app, metric filters on the JSON logs, alarms to an SNS topic, a dashboard |

The application settings come from the environment that `aws-dev` and `aws-prod` pass to the
service module: `ENVIRONMENT=production`, `SQLAGENT_CLOUD=aws`, `KEY_MODE=kms` with the
module's key alias, `STORAGE=s3`, `MAIL_BACKEND=ses`, `COOKIE_SECURE=true`, `CORS_ORIGINS`
and `PUBLIC_URL` from your host name, `FORWARDED_ALLOW_IPS` set to the VPC range,
`WORK_DIR=/tmp/work` on the task's ephemeral storage, and database pool sizes. Extra
non-secret settings go in `api_extra_environment` in `terraform.tfvars`, for example
`{ WORKER_CONCURRENCY = "8", RETENTION_DAYS = "90" }` (see
[configuration.md](configuration.md)). Never put secrets there.

## Network reach to your databases and model providers

The API (connection tests, schema discovery), the worker (queries) and the scheduler
(schema refresh) open connections to the databases people connect. By default they may
reach any address on PostgreSQL 5432 and MySQL 3306; set `source_cidrs` in
`terraform.tfvars` to the networks your databases are in. Databases in another VPC need
peering, a transit gateway or a private link to this VPC. SQLite databases are uploaded,
so they need no network path.

The API and the worker call model providers over HTTPS 443. A self-hosted model inside your
network on another port (Ollama on 11434, vLLM) needs an `ai_egress` entry, for example
`[{ cidr = "10.0.0.0/16", port = 11434 }]`.

## Before you start

- Terraform 1.16 (`hashicorp/terraform:1.16.6` is the pinned image), Docker with buildx,
  the AWS CLI with credentials for the target account, and `python3` (the deploy scripts use
  it to read Terraform outputs).
- A domain, an ACM certificate for the host name in the same region, and ideally a Route53
  hosted zone.
- SES out of the sandbox before notice mail goes to unverified recipients (request
  production access).

## Deploy

```bash
cd infra/terraform/envs/aws-dev
cp terraform.tfvars.example terraform.tfvars   # region, name prefix, host name, certificate, mail domain, image tag
cp backend.tf.example backend.tf               # optional but recommended: remote state in S3
cd -
make aws-deploy ENV=aws-dev TAG=0.1.0
```

In `terraform.tfvars`, `name_prefix` must be at most 24 characters and globally unique,
because the objects bucket is named `<name_prefix>-objects`. Replace every placeholder
(`<ACM_CERTIFICATE_ARN>`, `<ROUTE53_HOSTED_ZONE_ID>`, the `example.com` names), or remove
`route53_zone_id` and create the DNS records yourself.

The state holds generated secrets (the database password, the cache AUTH token, the
signing secrets). `backend.tf.example` keeps it in S3 with `encrypt = true` and S3-native
locking (`use_lockfile = true`); the state bucket must be private, versioned and encrypted,
with access limited to the people who deploy.

`scripts/aws-deploy.sh` then:

1. applies the image registries (and the KMS key that encrypts them);
2. builds the `api` and `web` images for the cluster's architecture (`linux/arm64`; set
   `PLATFORM` to change it) and pushes them;
3. applies everything else with that image tag;
4. runs the database migrations as a one-off ECS task (`scripts/aws-run-task.sh <env>
   migrate`);
5. waits for the api, worker, scheduler and web services to become stable, and prints the
   URL.

ECR tags are immutable: every deploy needs a new `TAG` (a release number or the git
commit).

## First admin

```bash
SQLAGENT_ADMIN_PASSWORD='...' make aws-admin ENV=aws-dev EMAIL=you@example.com
```

This runs `sqlagent create-admin` as a one-off task on the `migrate` task definition. The
password travels as an environment override, never on the command line, and must have at
least 10 characters with upper and lower case letters and a digit. Running it again for
the same email resets the password and makes the account an admin.

Or open the site and sign up: the first account on a fresh instance becomes the admin, and
sign-up is closed after it unless an admin opens it.

Other one-off commands:

| Command | What it does |
| --- | --- |
| `make aws-migrate ENV=...` | Runs `sqlagent migrate` again (after an upgrade) |
| `make aws-plan ENV=...` | `terraform plan` for the environment |
| `scripts/aws-run-task.sh <env> <command...>` | Any `sqlagent` command on the migrate task definition; prints the last log lines and the exit code |

Do not run `seed-demo` on a deployment that holds real work: it deletes every organization,
project, connection and conversation on the instance before it builds the demo.

## DNS, certificate and mail

- **DNS**: with `route53_zone_id`, Terraform creates the alias record for the host name.
  Without it, point a CNAME at the `load_balancer_dns_name` output.
- **Certificate**: `certificate_arn` must be an ACM certificate in the same region that
  covers `hostname`. Request and validate it before you apply.
- **SES**: with a Route53 zone the DKIM records are published for you; otherwise add the
  CNAMEs from the `dkim_records` output. New accounts start in the SES sandbox: request
  production access before mail goes to addresses you have not verified.

## `aws-dev` and `aws-prod`

Both use the same modules; compare the two `main.tf` files before you choose.

| | `aws-dev` | `aws-prod` |
| --- | --- | --- |
| Availability zones, NAT | 2, one shared NAT | 3, one NAT per zone |
| Interface endpoints | off | on |
| Database | `db.t4g.small`, single-AZ, 20 GiB (autoscaling to 100), 3 days of backups, no deletion protection | `db.t4g.medium`, Multi-AZ, 50 GiB (to 500), 14 days of backups, deletion protection, final snapshot |
| Cache | `cache.t4g.micro`, one node | `cache.t4g.small`, primary and replica with failover, 7 days of snapshots |
| api tasks | 0.5 vCPU, 1 GiB, 1 to 2 | 1 vCPU, 2 GiB, 2 to 6 |
| web tasks | 1 to 2 | 2 to 4 |
| worker tasks | 1 (0.5 vCPU, 1 GiB) | 2 (1 vCPU, 2 GiB) |
| scheduler | exactly one task | exactly one task |
| Pool per process (`DB_POOL_SIZE` + `DB_MAX_OVERFLOW`) | 5 + 10 | 10 + 20 |
| Log retention | 14 days | 365 days |
| KMS deletion window | 7 days | 30 days |
| Bucket and registries | may be destroyed with contents | protected |

The worker count is not autoscaled. Raise `worker_count` in `main.tf`, or
`WORKER_CONCURRENCY` through `api_extra_environment`, when the queue backs up
([operations.md](operations.md#scaling)). Keep (api tasks + worker tasks + scheduler +
migrate) x (pool + overflow) under the database's connection limit.

## Alarms

The `observability` module sends every alarm to one SNS topic; set `alarm_email` to
subscribe an address (confirm the mail AWS sends), or subscribe something else to the
topic.

| Alarm | Default threshold |
| --- | --- |
| 5xx responses, per app and at the load balancer | 25 in 5 minutes |
| API p95 time to first byte | 30 s (asking a question waits up to 60 s for its answer) |
| Unhealthy targets | more than 0 |
| CPU and memory per service (api, worker, scheduler, web) | 85 percent |
| Database CPU | 80 percent |
| Database free storage | below 5 GiB |
| Database connections | 80 percent of `db_max_connections` (100 dev, 400 prod) |
| Cache memory and engine CPU, per node | 80 percent |
| Failed questions (`question finished` with status `failed`) | `question_failure_threshold`, 10 in 5 minutes |
| SQL guard refusals (`query refused`) | `query_refusal_threshold`, 20 in 15 minutes. A spike can mean someone probing the guard |
| Question backlog (`queued` field of `question queue`) | `queue_backlog_threshold`, 50 sustained for 15 minutes (workers down or saturated) |
| Worker or scheduler error lines | 5 in 5 minutes |

The three question thresholds are variables in `terraform.tfvars`. The worker's Prometheus
metrics stay inside its task; these alarms read the structured logs instead
([operations.md](operations.md#metrics)).

## Proving the plan without an account

```bash
make tf-validate tf-lint tf-security   # validate, tflint and checkov on every environment
make tf-aws-on-floci                   # plan, apply, re-plan and destroy aws-dev against Floci
```

`make tf-aws-on-floci` copies the Terraform tree to a temp directory, starts a throwaway
Floci on port 5496 (`TF_FLOCI_PORT` moves it), requests a certificate from the emulator's
ACM and runs the real `aws-dev` configuration against it. It catches plan-time and
apply-time errors that `validate` cannot see. A few attributes the emulator does not store
show as in-place updates on the re-plan; the script's header lists them. `KEEP_FLOCI=1`
keeps the emulator and the work directory after a failure.

## After deploying

- Subscribe to the alarm topic.
- To scrape the API's `/metrics` from your Prometheus, list its address in
  `metrics_allowed_cidrs`; otherwise `/metrics` answers 404 at the load balancer.
- Restrict `source_cidrs` to your database networks.
- Read [operations.md](operations.md) for backups, scaling, retention and upgrades.
