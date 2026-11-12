# Operations

SQLAgent runs as four long-lived processes from one image plus the web app:

| Process | Command | Replicas |
| --- | --- | --- |
| API | `sqlagent serve` | Any number; stateless |
| Question worker | `sqlagent worker` | Any number; questions are claimed with `FOR UPDATE SKIP LOCKED` and leased |
| Scheduler | `sqlagent scheduler` | Exactly one |
| Web | Next.js server | Any number |
| Migrations | `sqlagent migrate` | One-off, before the others start |

## Health

| Endpoint | Meaning |
| --- | --- |
| `GET /healthz` (and `/health`, which adds the version) | The API process is up |
| `GET /readyz` | Postgres answers `select 1` within 2 s (503 otherwise). Redis, when configured, is probed and reported; its failure shows as `degraded` with 200, because rate limits and caches fall back to process memory |
| `GET /api/v1/system` (instance admins) | Version, environment, storage, key mode, cache and mail backends, whether Redis answers, the queue (`queued`, `running`, `oldest_queued_s`), and counts of organizations, projects, users, connections, conversations and executions. The admin **System** page shows the same |
| Worker `:9464/metrics` | The worker serves no HTTP API; Compose treats it as healthy while its metrics endpoint answers |
| Web `/api/healthz` | The Next.js server is up (its own route, not proxied) |

The web app also proxies `/healthz` and `/readyz` to the API, so a load balancer in front of
the web origin can probe both.

## Metrics

Prometheus metrics on the API's `/metrics` and on the worker's `WORKER_METRICS_PORT`
(default 9464). Each process has its own registry, so scrape every API and worker replica.
Several series come from both: the API calls the model for the generate and explain
endpoints and runs queries for the execute endpoint, the worker does both for questions.

| Metric | Type | Labels | Produced by | Meaning |
| --- | --- | --- | --- | --- |
| `sqlagent_questions_total` | counter | `status` | worker | Questions that reached a final state: `answered`, `refused`, `failed`, `no_answer` |
| `sqlagent_question_seconds` | histogram | | worker | Question duration from claim to final state (model, guard, execution) |
| `sqlagent_guard_refusals_total` | counter | `code` | api, worker | Queries the SQL guard refused, by rule (`not_a_select`, `write_or_admin`, ...) |
| `sqlagent_guard_seconds` | histogram | | api, worker | Time the guard spends parsing and checking one query |
| `sqlagent_executions_total` | counter | `dialect`, `status` | api, worker | Queries against connected databases by dialect and `succeeded`, `refused`, `scan_limit`, `timeout`, `failed` |
| `sqlagent_model_calls_total` | counter | `kind`, `outcome` | api, worker | Model calls by provider kind, `ok` or `error` |
| `sqlagent_model_latency_seconds` | histogram | `kind` | api, worker | Model call latency |
| `sqlagent_tokens_total` | counter | `direction` | api, worker | Model tokens, `input` and `output` |
| `sqlagent_queue_depth` | gauge | `status` | scheduler | `queued`, `running` and `oldest_wait_s`, refreshed every `TASK_INTERVAL_S` |
| `sqlagent_schema_refreshes_total` | counter | `outcome` | scheduler | Scheduled schema rediscoveries, `ok` or `failed` |
| `sqlagent_dependency_errors_total` | counter | `dependency`, `operation` | api, worker | Cache (Redis) calls that failed and fell back: `schema_read`, `schema_write`, `result_read`, `result_write`, `rate_limit` |

The scheduler's two series are only scrapeable if the scheduler gets a metrics port: Compose
sets `WORKER_METRICS_PORT=0` for it, and on AWS it has none. Watch the queue through
`/api/v1/system` or the `question queue` log line instead.

On AWS the worker's metrics stay inside its task. The `observability` module derives
CloudWatch metrics from the JSON logs (`QuestionsFinished`, `QuestionsFailed`,
`QueryRefusals`, `QuestionsQueued`, `WorkerErrors`, `SchedulerErrors`) and alarms on them
([deploy-aws.md](deploy-aws.md#alarms)).

## Logs

Every process writes one JSON object per line to stdout with `ts`, `level`, `logger`, `msg`
and the extra fields of the line. API lines carry a `request_id` (`x-request-id` is accepted
from the caller or generated, and returned). Fields named like credentials (`password`,
`token`, `api_key`, `secret`, `authorization`) are redacted, and so are `token=` query
parameters.

| `msg` | Process | Fields | Read by |
| --- | --- | --- | --- |
| `request` | api | `method`, `path`, `status`, `ms` | |
| `question finished` | worker | `status`, `total_ms`, `message_id` | `QuestionsFinished`, `QuestionsFailed` (status `failed`) |
| `query refused` | api, worker | `code`, `connection` | `QueryRefusals` |
| `query timed out` | api, worker | `connection`, `error` | |
| `question queue` | scheduler | `queued`, `running`, `oldest_wait_s` (once per tick) | `QuestionsQueued` |
| `schema refresh failed` | scheduler | `connection`, `error` | |
| `task done` | scheduler | `task`, `items` | |
| `lease lost before finishing` | worker | `message_id` | |

Any line with `level` = `error` from the worker or the scheduler counts towards the error
alarms.

## Scaling

| Signal | Action |
| --- | --- |
| `queued` stays above zero, or `oldest_queued_s` grows (`/api/v1/system`) | More worker capacity: raise `WORKER_CONCURRENCY` (questions per worker, default 8) or run more worker replicas |
| API CPU or latency | More API replicas. On AWS the api service autoscales on CPU between `api_min_count` and `api_max_count` |
| More than one API or worker replica | Run Redis (`REDIS_URL`), so rate limits are shared and the "new question" and "question finished" wake-ups cross processes. Without it everything still works, by polling |
| A connected database is under load from questions | Lower that connection's `timeout_s` and `max_scan_rows`, or point the connection at a read replica |

The API runs one uvicorn process per container (so `/metrics` stays exact); scale with
containers, not with uvicorn workers. Workers are safe to run side by side: a question is
claimed with `FOR UPDATE SKIP LOCKED`, held under a lease of `LEASE_S`, and finished with a
compare-and-set on the lease owner, so a question is never answered twice even after the
reaper hands it to another worker.

Run exactly one scheduler. Its tasks claim rows or are idempotent, so a brief overlap during
a deployment does no harm, but extra schedulers add load without adding anything. On AWS
the scheduler is deployed with minimum healthy 0 and maximum 100 percent, so two never run
side by side.

Connections: every process holds a pool of up to `DB_POOL_SIZE + DB_MAX_OVERFLOW` to
SQLAgent's Postgres; keep (API replicas + worker replicas + scheduler + migrate) x that
number under the database's connection limit. Each running question also holds one
connection to the connected database, opened for that question and closed after it, so
(worker replicas x `WORKER_CONCURRENCY`) is the most connections the workers open to any
one database at once.

Locally: `SQLAGENT_WORKER_CONCURRENCY=16` in `deploy/compose/.env`, or
`docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml -f deploy/compose/compose.floci.yaml up -d --scale worker=3`.
On AWS: `worker_count` in the environment's `main.tf`, and `WORKER_CONCURRENCY` in
`api_extra_environment`.

## Retention

The scheduler's `retention` task runs every `TASK_INTERVAL_S` and deletes, older than
`RETENTION_DAYS` (default 90):

- query executions, up to 500 per tick, together with their result snapshots in object
  storage (a snapshot that fails to delete is logged as `snapshot delete failed` and the row
  is removed anyway);
- conversations whose last message is older than the cutoff, with their messages.

The audit log is never purged. It is append-only in the database itself: a trigger
(`audit_log_no_change`) raises `audit_log is append-only` on any `UPDATE` or `DELETE`, so
every query that ever ran, and who ran it, stays on record even after its execution row
and snapshot are gone. Plan database storage for it: it grows with every question.

Uploaded SQLite databases are kept as long as their connection exists; deleting the
connection deletes the file.

## Backup and restore

Locally:

```bash
make backup                                   # backups/<timestamp>/: pg_dump + the objects bucket
make restore BACKUP=backups/20261112T060000Z  # stops api, worker, scheduler and web, restores, starts them
```

`scripts/backup.sh` takes a `pg_dump --format=custom` (one transaction, so it is consistent
while the app keeps serving) and syncs the `sqlagent-local-objects` bucket from Floci.
`scripts/restore.sh` stops the api, worker, scheduler and web, runs `pg_restore --clean
--if-exists --no-owner`, syncs the objects back and starts the services again. Both expect
the stack started by `make up`.

On AWS: RDS automated backups and snapshots (3 days in `aws-dev`, 14 in `aws-prod`, plus a
final snapshot on destroy in prod), and S3 versioning with replaced or deleted object
versions kept for `noncurrent_retention_days` (30). Back up the secrets too: without the
KMS key (or `LOCAL_MASTER_KEY` in local mode) a restored database has unreadable connection
passwords and provider keys, and without the original `API_KEY_PEPPER` every API key stops
working. The KMS key has a deletion window; never schedule its deletion while data sealed by
it exists.

## Upgrading

1. Read the release notes.
2. Back up.
3. Deploy the new image. Locally, `make up` rebuilds the images and runs `migrate` to
   completion before the api, worker and scheduler start. On AWS,
   `make aws-deploy ENV=... TAG=<new>` runs migrations as a one-off task before the services
   roll; `make aws-migrate ENV=...` runs them again on their own.
4. Migrations are forward-only Alembic revisions (`sqlagent migrate` applies them), never
   edited once released.

Workers stop gracefully on SIGTERM: they stop claiming and give running questions 25 seconds
to finish. If a worker is killed mid-question, its lease expires and another worker answers
the question again; after `MAX_ATTEMPTS` (3) claims it fails with `worker_lost`. The API
allows 30 seconds for in-flight requests on shutdown.

## Rotating secrets and keys

| Secret | Effect of rotating |
| --- | --- |
| `SESSION_SECRET` | Every session ends; people sign in again |
| `API_KEY_PEPPER` | Every API key stops working; project admins create new keys |
| `LOCAL_MASTER_KEY` (`KEY_MODE=local`) | Sealed values become unreadable: re-enter every connection password and model provider key and header. Prefer `KEY_MODE=kms` |
| KMS key (`KEY_MODE=kms`) | Nothing to do: the `kms` module turns on annual rotation, and KMS keeps old key material to open values sealed before it |
| Switching `KEY_MODE` between `local` and `kms` | Like rotating `LOCAL_MASTER_KEY`: values sealed under one mode cannot be opened by the other |
| A connected database's password | Edit the connection and enter the new password; it is sealed again |
| A model provider's API key | Edit the provider and enter the new key |

Locally the three secrets live in `deploy/compose/.env`; change them there and recreate the
containers. On AWS `SESSION_SECRET` and `API_KEY_PEPPER` are in the Secrets Manager entry
`<name_prefix>/app`; Terraform generates them once and never rolls them back, so rotate the
value in Secrets Manager and force a new deployment of the api, worker and scheduler (ECS
reads secrets when a task starts).

## Common admin tasks

| Task | How |
| --- | --- |
| Create or reset an admin | `make admin EMAIL=you@example.com` locally (prompts for the password); `make aws-admin ENV=... EMAIL=...` on AWS with `SQLAGENT_ADMIN_PASSWORD` set. Both run `sqlagent create-admin`, which also re-enables a disabled account and ends its sessions |
| Open or close self sign-up | Admin, **Settings** |
| See queue and deployment state | Admin, **System** |
| See who ran what | **Audit** (instance-wide for admins, per project for members); append-only |
| Find why a question failed | The question shows its error and code; `make logs SERVICE=worker` has the details |
| Rediscover a schema now | The connection page, or `POST /api/v1/projects/{pid}/connections/{cid}/schema/refresh` (project editors) |
| Reset the local demo | `make demo`. It deletes every organization, project, connection and conversation before building the demo, so never point it at an instance with real work |
