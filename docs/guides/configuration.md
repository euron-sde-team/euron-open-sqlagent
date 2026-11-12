# Configuration

Every setting of the API, the question worker and the scheduler is an environment variable,
read once at start and validated (`apps/api/src/sqlagent/core/config.py`); names are
case-insensitive. The three processes and the one-off `migrate` task read the same
`Settings`, so give them the same environment.

Settings that belong to a project, a connection or a model provider are not environment
variables: they are edited in the app ([below](#settings-in-the-app)).

## Production boot guards

With `ENVIRONMENT=production`, `guard()` runs at start and the process refuses to boot with
`unsafe production configuration: ...`, listing every problem it found:

| Rule | Message |
| --- | --- |
| `SESSION_SECRET` and `API_KEY_PEPPER` are random and long | `SESSION_SECRET must be a random value of at least 32 chars` (and the same for `API_KEY_PEPPER`) |
| With `KEY_MODE=local`, `LOCAL_MASTER_KEY` is random and long | `LOCAL_MASTER_KEY must be set (or use KEY_MODE=kms)` |
| The two signing secrets differ | `SESSION_SECRET and API_KEY_PEPPER must differ` |
| No endpoint override on real AWS | `AWS_ENDPOINT_URL must be unset when SQLAGENT_CLOUD=aws` |
| Secure cookies | `COOKIE_SECURE must be true in production` |
| Real mail | `MAIL_BACKEND must be smtp or ses in production` |
| Shared object storage | `STORAGE must be s3 in production (several replicas share result snapshots)` |

A secret counts as insecure when it is shorter than 32 characters, contains
`not-for-production` (every built-in default does), or is one of `change-me`, `dev`,
`secret`, `replace-with-output-of-make-env` or empty. In `development` and `test` the guard
does nothing, which is why the local stack runs with `ENVIRONMENT=development`: it talks to
an emulator and links to `http://localhost`, both of which production refuses on purpose.

## API, worker and scheduler (`Settings`)

### Runtime and database

| Variable | Default | Meaning |
| --- | --- | --- |
| `ENVIRONMENT` | `development` | `development`, `test` or `production` (production enables the guards above) |
| `LOG_LEVEL` | `INFO` | Level of the JSON logs on stdout |
| `SQLAGENT_CLOUD` | `local` | `local`, `floci` or `aws`: where AWS calls go. Informational, plus the endpoint guard above |
| `DATABASE_URL` | `postgresql+asyncpg://sqlagent:sqlagent@localhost:5442/sqlagent` | SQLAgent's own Postgres (asyncpg driver). It also holds the question queue |
| `DB_POOL_SIZE` | `10` | Connections kept open per process |
| `DB_MAX_OVERFLOW` | `20` | Extra connections a process may open under load |
| `REDIS_URL` | empty | Rate limits, caches and the pub/sub wake-ups between the API and the workers. Optional: empty keeps them in process memory, which is exact only for one replica of each process |
| `MEMORY_CACHE_MAX_BYTES` | `64000000` | Byte budget of the in-process cache used without Redis (at least 1,000,000) |
| `OTEL_ENABLED` | `false` | Install an OpenTelemetry SDK with an OTLP exporter, configured by the standard `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_SERVICE_NAME` |

Without Redis, a worker in another process does not hear the "new question" wake-up and
finds the question on its next poll (`WORKER_POLL_INTERVAL_S`), so answers arrive up to a
couple of seconds later. Nothing is lost: the queue is in Postgres.

### Sessions and links

| Variable | Default | Meaning |
| --- | --- | --- |
| `SESSION_SECRET` | dev value | Signs session tokens. At least 32 random characters in production |
| `API_KEY_PEPPER` | dev value | HMAC key for API key hashes. At least 32 random characters, different from `SESSION_SECRET` |
| `SESSION_TTL_HOURS` | `12` | Session lifetime |
| `COOKIE_SECURE` | `false` | Secure flag on the `sqa_session` cookie; must be `true` in production |
| `CORS_ORIGINS` | `http://localhost:5410` | Comma separated origins allowed to call the API from a browser |
| `PUBLIC_URL` | `http://localhost:5410` | Where people open the app; used for links in notice mail |
| `MAX_BODY_BYTES` | `2000000` | Request body limit for ordinary routes (413 above it) |
| `QUESTION_RPM` | `120` | Questions per project per minute (at least 1) |

### Sealing, AWS and storage

Connection passwords, model provider API keys and provider headers are sealed before they
reach Postgres.

| Variable | Default | Meaning |
| --- | --- | --- |
| `KEY_MODE` | `local` | `local` (AES-256-GCM with a key derived from `LOCAL_MASTER_KEY`) or `kms` |
| `LOCAL_MASTER_KEY` | dev value | Key material for `KEY_MODE=local`. Losing it makes every sealed password and key unreadable |
| `KMS_KEY_ID` | `alias/sqlagent-local` | The KMS key or alias for `KEY_MODE=kms`. Each value is sealed with an encryption context bound to its row |
| `AWS_REGION` | `us-east-1` | Region for KMS, S3 and SES |
| `AWS_ENDPOINT_URL` | unset | An AWS-compatible endpoint (Floci locally). Must be unset with `SQLAGENT_CLOUD=aws` in production |
| `S3_FORCE_PATH_STYLE` | `false` | Path-style S3 addressing (needed by the emulator) |
| `STORAGE` | `local` | `local` (a directory) or `s3`. Production requires `s3`, because every replica must read the same result snapshots |
| `LOCAL_STORAGE_DIR` | `./.data/objects` | Directory for `STORAGE=local` |
| `OBJECTS_BUCKET` | `sqlagent-local-objects` | Bucket for `STORAGE=s3`: uploaded SQLite databases and query result snapshots (result pages and CSV exports are read from them). Rows keep only the key |
| `WORK_DIR` | `./.data/work` | Temp files: SQLite uploads while they stream in, and the local read-only copies of SQLite databases that queries open |
| `MAX_UPLOAD_BYTES` | `200000000` | Largest SQLite upload (at least 1,000,000). Applies only to signed-in callers; anonymous requests keep `MAX_BODY_BYTES` |

AWS credentials come from the standard chain (task role, profile, environment); nothing in
the app reads a static key.

### Mail

SQLAgent sends one kind of mail: a notice when someone is added to a project.

| Variable | Default | Meaning |
| --- | --- | --- |
| `MAIL_BACKEND` | `log` | `log` (written to the log; development and tests), `smtp` or `ses`. Production refuses `log` |
| `MAIL_FROM` | `SQLAgent <sqlagent@sqlagent.local>` | Sender of notice mail |
| `SMTP_HOST` | `localhost` | SMTP relay for `MAIL_BACKEND=smtp` (the Compose stack uses `mailpit`) |
| `SMTP_PORT` | `1025` | SMTP port (1 to 65535) |

### Connected databases and model providers

| Variable | Default | Meaning |
| --- | --- | --- |
| `SOURCE_ALLOW_PRIVATE` | `true` | Database hosts may resolve to private and loopback addresses (databases usually live on private networks). Link-local and instance metadata addresses are always refused |
| `PROVIDER_ALLOW_PRIVATE` | `true` | A model provider's base URL may be a private host (a local Ollama or vLLM). Metadata addresses are always refused |
| `MAX_ROWS_CEILING` | `100000` | Upper bound of any connection's `max_rows` (at least 10) |
| `MAX_TIMEOUT_CEILING_S` | `600` | Upper bound of any connection's `timeout_s` (1 to 3,600) |
| `SCHEMA_MAX_TABLES` | `2000` | Tables and views read per connection during schema discovery (10 to 50,000) |
| `PROMPT_SCHEMA_CHARS` | `24000` | Character budget of the schema part of a prompt; the tables most relevant to the question go first (2,000 to 400,000) |
| `HISTORY_TURNS` | `6` | Earlier turns of a conversation given to the model for follow-up questions (0 to 50) |
| `SCHEMA_REFRESH_HOURS` | `24` | The scheduler rediscovers a cached schema older than this (up to 720) |
| `MODEL_TIMEOUT_S` | `120` | Cap on a model call; a provider's own timeout is lowered to it (up to 1,800) |

### Question worker and scheduler

| Variable | Default | Meaning |
| --- | --- | --- |
| `WORKER_CONCURRENCY` | `8` | Questions one worker answers at once (1 to 256) |
| `LEASE_S` | `60` | Lease on a claimed question. A question whose lease expires goes back to the queue (10 to 3,600) |
| `MAX_ATTEMPTS` | `3` | Claims before a question whose worker keeps dying is failed with `worker_lost` (1 to 20) |
| `WORKER_POLL_INTERVAL_S` | `2` | How long an idle worker waits before looking at the queue again (up to 60) |
| `TASK_INTERVAL_S` | `10` | How often the scheduler runs its periodic tasks: lease reaper, schema refresh, retention, queue gauges (up to 600) |
| `WORKER_METRICS_PORT` | `9464` | Prometheus endpoint of the worker (and of the scheduler); `0` disables it |
| `RETENTION_DAYS` | `90` | Conversations, query executions and their result snapshots older than this are deleted by the scheduler (at least 1). The audit log is never purged |

## Process and container variables

These are read by the command line, not by `Settings`.

| Variable | Default | Used by | Meaning |
| --- | --- | --- | --- |
| `PORT` | `8080` | `sqlagent serve` | Listening port of the API (`--port` overrides it) |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | `sqlagent serve` | Addresses whose `X-Forwarded-For` is trusted (the Compose network uses `*`, AWS the VPC CIDR) |
| `SQLAGENT_ADMIN_PASSWORD` | prompt | `sqlagent create-admin` | The password, instead of a prompt (for one-off tasks). At least 10 characters with upper and lower case letters and a digit |
| `API_INTERNAL_URL` | `http://localhost:5430` | web | Where the Next.js server proxies `/api/*`, `/healthz`, `/readyz`, `/docs` and `/openapi.json` (server side only; the browser never sees it) |

The web app (`apps/web/next.config.ts`) is same-origin: the browser only talks to the web
origin, Next proxies the API paths to `API_INTERNAL_URL`, so the `httpOnly` session cookie
stays first-party and no CORS is needed. The proxy waits up to 120 seconds. Its own
`/api/healthz` route answers without the API. For `pnpm dev` outside Docker, copy
`apps/web/.env.example` to `apps/web/.env.local`; it holds only `API_INTERNAL_URL`. In
Compose it is `http://api:8080`; on AWS the service module sets it to the API's private
Cloud Map address.

## Local stack (`deploy/compose/.env`)

Generated by `make env` (`scripts/gen-local-env.sh`) with random values, and never
overwritten (delete the file to regenerate it, then `make down` so the databases match).
It is git-ignored; `deploy/compose/.env.example` shows its shape.

| Variable | Meaning |
| --- | --- |
| `SESSION_SECRET`, `API_KEY_PEPPER`, `LOCAL_MASTER_KEY` | The secrets above, 64 random characters each |
| `SQLAGENT_DEMO_PASSWORD` | Password of every demo account |
| `SQLAGENT_SOURCE_ADMIN_PASSWORD` | Admin password of the demo databases (the seed writes their data with it) |
| `SQLAGENT_READER_PASSWORD` | Password of the read-only login the demo connections use |
| `SQLAGENT_LOG_LEVEL` | Passed to the containers as `LOG_LEVEL` |
| `SQLAGENT_WORKER_CONCURRENCY` | Passed to the worker as `WORKER_CONCURRENCY` (default 8) |

Host ports, all bound to `127.0.0.1` and overridable in the same file:

| Variable | Default | Service |
| --- | --- | --- |
| `SQLAGENT_WEB_PORT` | 5410 | Web app (also sets `CORS_ORIGINS` and `PUBLIC_URL`) |
| `SQLAGENT_API_PORT` | 5430 | API (`/docs` for the OpenAPI UI) |
| `SQLAGENT_PG_PORT` | 5442 | SQLAgent's Postgres |
| `SQLAGENT_REDIS_PORT` | 5479 | Redis |
| `SQLAGENT_FLOCI_PORT` | 5466 | Floci (emulated S3, KMS, Secrets Manager, SES) |
| `SQLAGENT_MAILPIT_PORT` | 5425 | Mailpit web UI |
| `SQLAGENT_MOCK_AI_PORT` | 5450 | Mock model provider (OpenAI, Anthropic, Gemini and Ollama wire formats) |
| `SQLAGENT_SOURCE_PG_PORT` | 5443 | Demo PostgreSQL (`shop`) |
| `SQLAGENT_SOURCE_MYSQL_PORT` | 5406 | Demo MySQL (`people`) |

`make tf-aws-on-floci` starts its own throwaway emulator on 5496; set `TF_FLOCI_PORT` to
move it.

The Compose file sets the rest: `ENVIRONMENT=development`, `REDIS_URL`, `MAIL_BACKEND=smtp`
to Mailpit, `FORWARDED_ALLOW_IPS=*`, `WORK_DIR` and `LOCAL_STORAGE_DIR` on volumes, and
`WORKER_METRICS_PORT=0` for the scheduler. The Floci overlay (`compose.floci.yaml`, used by
`make up`) switches to `SQLAGENT_CLOUD=floci`, `STORAGE=s3`, `KEY_MODE=kms` and
`AWS_ENDPOINT_URL=http://floci:4566`. The demo seed (`sqlagent seed-demo`) also reads
`SQLAGENT_DEMO_READER_PASSWORD`, `SQLAGENT_DEMO_SOURCE_PG_ADMIN`,
`SQLAGENT_DEMO_SOURCE_MYSQL_ADMIN` and `SQLAGENT_DEMO_MOCK_URL` (default
`http://mock-ai:5450`), which Compose sets. For `make up-aws`, `deploy/compose/.env.aws`
holds `AWS_REGION`, optionally `AWS_PROFILE`, `OBJECTS_BUCKET` and `KMS_KEY_ID`
([local-with-aws.md](local-with-aws.md)).

## Settings in the app

### Connection limits

Every connection carries its own limits, set when it is created and editable later by a
project editor (`apps/api/src/sqlagent/connections/schemas.py`):

| Field | Default | Range | Meaning |
| --- | --- | --- | --- |
| `max_rows` | 1,000 | 1 to 100,000 | Rows a result may return. More rows are cut off and the result is marked truncated |
| `max_scan_rows` | 10,000,000 | 1 to 10,000,000,000 | Rows the database's planner may expect to read, from `EXPLAIN` (never `EXPLAIN ANALYZE`). A bigger plan is refused with status `scan_limit` before it runs |
| `timeout_s` | 30 | 1 to 600 | Seconds a statement may run, enforced by the database (`statement_timeout` on PostgreSQL, `MAX_EXECUTION_TIME` on MySQL, a progress handler on SQLite). Past it the status is `timeout` |
| `sample_values` | off | on or off | During schema discovery, read the distinct values of low-cardinality text columns so the model can use their real spelling |

The server ceilings apply on top: a `max_rows` above `MAX_ROWS_CEILING` is stored as the
ceiling, and so is a `timeout_s` above `MAX_TIMEOUT_CEILING_S`. Lowering a ceiling affects
connections saved or edited afterwards; existing rows keep their stored values until they
are edited. `max_scan_rows` has no server ceiling.

With `sample_values` on, discovery reads up to 12 distinct values per text column (only
when the column has no more than 12, and not for primary keys), only in tables of at most
2,000,000 rows. The values go into the prompt sent to the model provider, so leave it off
for columns that hold personal data.

### Other settings

| Scope | Setting | Default | Who |
| --- | --- | --- | --- |
| Instance | Site name, open self sign-up | sign-up closed (the first account on a fresh instance may always sign up and becomes the admin) | Instance admin |
| Project | Model providers: kind (`openai`, `anthropic`, `gemini`, `ollama`, `openai_compatible`, `mock`), model, base URL, API key (sealed), extra headers (sealed), timeout, enabled, default | timeout 60 s, capped by `MODEL_TIMEOUT_S` | Project admin |
| Connection | Host, port, database, user, password (sealed, write-only), SSL mode (`disable`, `prefer`, `require`, `verify-full`), default schema, description given to the model | port 5432 or 3306, `prefer` | Project editor |
