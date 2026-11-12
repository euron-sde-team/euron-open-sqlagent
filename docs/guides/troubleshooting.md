# Troubleshooting

Messages below are quoted from the code, so you can search for them. Errors from the API come
as `{"error": {"code", "type", "message", "details"}}`; the `code` is stable and listed where
it helps. A question that fails keeps its `error` and `error_code` on the message, and every
query that ran or was refused is in the audit log.

## Starting the stack

| Symptom | Cause | Fix |
| --- | --- | --- |
| `make up` fails with "port is already allocated" or "address already in use" | Something else uses one of the host ports: web 5410, api 5430, postgres 5442, redis 5479, floci 5466, mailpit 5425, mock model provider 5450, demo PostgreSQL 5443, demo MySQL 5406 | Set the matching `SQLAGENT_*_PORT` in `deploy/compose/.env` ([configuration.md](configuration.md#local-stack-deploycomposeenv)) and run `make up` again |
| `make tf-aws-on-floci` cannot start its emulator | Port 5496 is taken | `TF_FLOCI_PORT=5497 make tf-aws-on-floci` |
| Compose says "run `make env` first" | `deploy/compose/.env` is missing a secret | `make env` (it never overwrites). After deleting and regenerating it, `make down` so the databases match the new passwords |
| `make up` stops at the `terraform` one-shot (`service "terraform" didn't complete successfully`) | The one-shot applies `infra/terraform/envs/local-floci` to Floci before migrate, api, worker and scheduler may start. Usual causes: Floci not up yet or its port taken, no network to download the AWS provider on the first run, or state left from an emulator that was reset on its own | `make logs SERVICE=terraform` shows the Terraform error. State and emulator data live in two volumes that `make down` deletes together, so `make down && make up` starts both clean |
| `migrate` exits non-zero | Postgres was not reachable, or a migration failed | `make logs SERVICE=migrate`; the api, worker and scheduler wait for it to succeed |
| The API exits with "unsafe production configuration: ..." | `ENVIRONMENT=production` with a demo or short secret, equal secrets, `COOKIE_SECURE=false`, `MAIL_BACKEND=log`, `STORAGE=local` or an endpoint override with `SQLAGENT_CLOUD=aws` | Fix every item the message lists; they are the boot guards in [configuration.md](configuration.md#production-boot-guards) |
| `make demo` stops with "SQLAGENT_DEMO_... is not set (run the seed inside the Compose stack: make demo)" | The seed ran outside Compose, which sets those variables | Run it through `make demo` |
| `make demo` fails right away | The worker container is not running (the seed runs inside it) | `make ps`; `make up` first |
| `make up-aws` says "copy deploy/compose/.env.aws.example to .env.aws first" | No `.env.aws` | See [local-with-aws.md](local-with-aws.md) |

## Model providers

| Message | Code | Cause | Fix |
| --- | --- | --- | --- |
| "This project has no model provider yet. An admin adds one under Settings, Model providers (the built-in mock works without a key)" | `no_provider` | The project has no enabled provider | A project admin adds one under **Settings**, **Model providers**. The `mock` kind needs no key and answers from the schema deterministically |
| "The provider answered 401: ..." (or 403) | `provider_auth` | The API key is wrong, expired or lacks access to the model | Edit the provider and enter a new key, then **Test** it (lists the provider's models with the stored key). Not retried |
| "The provider answered 404: ..." | `model_not_found` | The model name does not exist for that key | Pick a model from the provider's **Test** result |
| "The provider answered 429: ..." | `rate_limited` | The provider's own rate limit | Retried twice with backoff (honouring `Retry-After` up to 30 s); then wait, or raise your quota with the provider |
| "The provider answered 5xx: ..." | `provider_unavailable` | The provider is overloaded or down | Retried twice; try again later |
| "The provider did not answer in time" | `provider_timeout` | Slower than the provider's timeout (default 60 s), capped by `MODEL_TIMEOUT_S` (120 s) | Raise the provider's timeout, or use a faster model |
| "Could not reach the provider: ConnectError" | `provider_unreachable` | DNS, network or base URL. From Docker, a model on your own machine is `host.docker.internal`, not `localhost`. On AWS, a self-hosted model on a port other than 443 needs `ai_egress` | Fix the base URL or the network path |
| "The provider URL is a private address, which this deployment does not allow (PROVIDER_ALLOW_PRIVATE=false)" | `provider_private` | A private base URL with `PROVIDER_ALLOW_PRIVATE=false` | Set it to `true`, or use a public endpoint |
| "The provider URL resolves to a forbidden address" | `provider_forbidden` | The host resolves to a link-local or metadata address | Always refused; use another host |
| "That model provider is turned off" / "The model provider is turned off" | `provider_disabled` | The provider is disabled | Enable it, or pick another |
| "An OpenAI-compatible provider needs its base URL" | `base_url_required` | `openai_compatible` without a base URL | Enter the URL of the compatible server |

## A question stays queued

The API waits up to 60 seconds for an answer and then returns the question as `queued` or
`running`; the page keeps polling. A question that stays `queued` has no worker to answer
it.

| Check | How |
| --- | --- |
| Is a worker running? | `make ps` (the `worker` service should be healthy); `make logs SERVICE=worker` |
| Is the queue backing up? | Admin, **System**: queued, running and the age of the oldest queued question |
| Are all workers busy? | `running` equals worker replicas x `WORKER_CONCURRENCY`. Raise either ([operations.md](operations.md#scaling)) |
| Did a worker die mid-question? | The scheduler's lease reaper returns it to the queue after `LEASE_S` (60 s). After 3 claims it fails with "The worker answering this question stopped 3 times. Ask again, and tell an admin if it keeps happening" (`worker_lost`). Check that the `scheduler` service runs, and the worker's memory |
| Asked too fast? | "This project asks more than 120 questions a minute. Try again in N s" (429) is `QUESTION_RPM` |

## Connections and schema discovery

The connection test and schema discovery turn driver errors into a sentence
(`apps/api/src/sqlagent/connections/service.py`, `friendly()`). A failed discovery keeps the
previous schema and records the error on it (`schema_discovery_failed`).

| Message | What to check |
| --- | --- |
| "The username or password was refused. Check them, and that the user may log in" | Credentials, and on PostgreSQL `pg_hba.conf` for SQLAgent's address |
| "The database name was not found on the server" | The database field (case matters on some servers) |
| "The host name could not be resolved. Check the spelling, or use an IP address" | DNS from the API and worker containers, not from your laptop. A database on your own machine is `host.docker.internal` from Docker Desktop; the demo databases are `source-postgres` and `source-mysql` |
| "Nothing answered on that host and port. Check the port, firewall and that the database is running" | Port, security groups (`source_cidrs` on AWS), that the server listens on a non-loopback address |
| "The connection timed out. Check that the database is reachable from this deployment" | Network path; on AWS, peering or routes to the database's VPC |
| "The SSL handshake failed (...). Try another SSL mode" | `ssl_mode`: `require` or `verify-full` for servers that demand TLS, `disable` for local test servers without it |
| "The database did not answer in time" | The test has a 20 s limit; the server is slow or unreachable |
| "The host resolves to an address this deployment refuses (metadata, or private when SOURCE_ALLOW_PRIVATE=false)" (`host_refused`) | The host resolves to a link-local or instance metadata address (always refused, checked again at every connect, so a DNS name pointing there is caught too), or to a private or loopback address with `SOURCE_ALLOW_PRIVATE=false` |
| "link-local and instance metadata addresses are not allowed" | The same rule, applied to the host as typed |
| "This SQLite connection has no database file" (`sqlite_missing`) | Upload the file again as a new connection |
| "A connection with this name exists in the project" (`name_taken`) | Names are unique per project |

| Symptom | Cause | Fix |
| --- | --- | --- |
| The test passes but tables are missing | The login cannot see them (no `USAGE` on the schema or no `SELECT`), they are in another schema than `default_schema`, or the database has more than `SCHEMA_MAX_TABLES` (2,000) tables and views | Grant read access, set or clear the default schema, or raise the limit; then **Refresh schema** |
| A new table or column is unknown to the model | The cached schema is older than the change. The scheduler rediscovers schemas older than `SCHEMA_REFRESH_HOURS` (24) | **Refresh schema** on the connection |
| The model ignores relevant tables in a large database | The schema part of the prompt is capped at `PROMPT_SCHEMA_CHARS` (24,000) characters, most relevant tables first | Raise it, add a connection description that names the key tables, or connect a narrower schema |

## Queries that did not run

### Refused by the SQL guard

Every query, from a model or pasted by a person, must be exactly one read-only `SELECT`
(with `UNION`, `INTERSECT`, `EXCEPT` and CTEs allowed). The guard
(`apps/api/src/sqlagent/sql/guard.py`) parses it in the connection's dialect; a refusal ends
with status `refused`, the reason and the rule's code.

| Code | Message | Typical cause |
| --- | --- | --- |
| `empty` | "the query is empty" | Nothing but whitespace or `;` |
| `too_long` | "the query is longer than 100,000 characters" | A generated or pasted query over the limit |
| `parse_error` | "the query does not parse: ..." or "the text does not read as a SQL statement" | A syntax error in the connection's dialect, or prose instead of SQL |
| `multiple_statements` | "exactly one statement is allowed, found 2" | Two statements separated by `;` |
| `not_a_select` | "only SELECT queries run, not INSERT" (or `UPDATE`, `DELETE`, `CREATE`, `SHOW`, ...) | The statement is not a query |
| `write_or_admin` | "LOCK is not allowed in a read-only query" (or `INTO`, `SET`, `PRAGMA`, ...) | A query that writes, locks rows (`FOR UPDATE`), changes session state or is wrapped around a write |
| `denied_function` | "the function pg_sleep is not allowed" | A function with side effects, sleeps, file or network access or session changes (`pg_read_file`, `dblink`, `set_config`, `nextval`, `sleep`, `load_file`, `load_extension`, ...). A name on any dialect's list is refused everywhere |
| `table_function` | "table functions and file paths are not allowed" | A function or a literal path in `FROM` |

A refused query never reaches the database. If a model keeps writing refused queries for
one question, rephrase it as a question about reading data. The `query refused` log line
and `sqlagent_guard_refusals_total{code}` count refusals; on AWS a spike raises an alarm.

### Stopped by the connection's limits

| Status | Message | Fix |
| --- | --- | --- |
| `scan_limit` | "The database expects this query to read about N rows, more than this connection allows (M). Narrow it with a filter or a smaller time range, or raise the connection's scan limit" | The planner's estimate (`EXPLAIN`, nothing runs) is above `max_scan_rows`. Add a filter, or raise `max_scan_rows` on the connection (project editors) |
| `timeout` | "The database stopped the query after N s, this connection's time limit. Narrow it, or raise the connection's timeout" | Raise `timeout_s` on the connection, up to `MAX_TIMEOUT_CEILING_S` (600 by default; raise that on the server first if you need more), or add an index for the filter |
| `succeeded`, marked truncated | The result had more rows than `max_rows` | Expected: add aggregation or a `LIMIT`, or raise `max_rows` up to `MAX_ROWS_CEILING` |
| `failed` with a database message | The query passed the guard but the database rejected it (an unknown column, a type error, a permission) | The message is the database's own first line; fix the query or grant `SELECT` |

A value above a ceiling is saved as the ceiling without an error. If a raised limit does
not stick, check `MAX_ROWS_CEILING` and `MAX_TIMEOUT_CEILING_S`.

### The model wrote no query, or the wrong filter

| Symptom | Cause | Fix |
| --- | --- | --- |
| Status `no_answer` with the model's explanation | The model found nothing in the schema that answers the question | Rephrase with table or column names, or add a connection description |
| A filter returns no rows, for example `status = 'Shipped'` where the data says `shipped` | Sample values are off (the default), so the model guesses the spelling | Turn on **sample values** for the connection, then **Refresh schema**. Discovery then reads up to 12 distinct values of low-cardinality text columns in tables up to 2,000,000 rows. Those values are sent to the model provider, so leave it off where columns hold personal data |
| "A follow-up stays on its conversation's connection; start a new conversation for another database" (`connection_mismatch`) | A follow-up named another connection | Start a new conversation |

## SQLite uploads

| Message | Code | Fix |
| --- | --- | --- |
| "This is not a SQLite database file" | `not_sqlite` | The file does not start with the SQLite header. Upload the database file itself, not a dump or an archive |
| "The file is empty" | `file_empty` | Upload the real file |
| "The file is larger than N bytes" | `file_too_large` | Over `MAX_UPLOAD_BYTES` (200,000,000 by default); raise it |
| "The request body is larger than N bytes. Shorten it, or raise MAX_BODY_BYTES (MAX_UPLOAD_BYTES for SQLite files)" (413) | `payload_too_large` | Over the body limit before the file was read. Uploads get `MAX_UPLOAD_BYTES` only with a valid session or API key; sign in (or send the key) first. On AWS the WAF and the load balancer idle timeout (120 s) also bound very slow uploads |

## Accounts and access

| Message | Code | Cause | Fix |
| --- | --- | --- | --- |
| "Too many sign-in attempts from this address. Wait a minute and try again" (429) | `rate_limited` | 20 sign-ins per minute per IP | Wait. Behind a proxy, check `FORWARDED_ALLOW_IPS`, or every user shares the proxy's address |
| "Too many failed attempts. Try again in a few minutes" | `account_locked` | 5 wrong passwords lock the account for 15 minutes | Wait, or an admin resets it (`make admin EMAIL=...`) |
| "Email or password is incorrect" | `invalid_credentials` | | Check the email; an admin can reset the password |
| "Missing CSRF header" (403) | `csrf_required` | A script using the `sqa_session` cookie for a `POST`, `PUT`, `PATCH` or `DELETE` without `X-SQA-CSRF: 1` | Send the header, or authenticate with `Authorization: Bearer <token>` or `X-API-Key: sqa_...`, which need no CSRF header |
| "Your session expired. Sign in again" | `session_expired` | Past `SESSION_TTL_HOURS`, signed out, password reset, or `SESSION_SECRET` rotated | Sign in again |
| "Sign-up is closed. Ask an administrator for an account" | `signup_closed` | Only the first account may sign up unless an admin opens sign-up | An admin creates the account, or opens sign-up in **Settings** |
| "Password needs at least 10 characters, upper and lower case letters, a digit" | `weak_password` | The password policy | Choose a longer, mixed password |
| "This API key lacks the 'query' scope" (or another scope) | `insufficient_scope` | The key was created without that scope | Create a key with the scope |
| "This action needs the editor role in this project" | `insufficient_role` | Viewers read conversations, results and schemas; editors also ask questions, run SQL and manage connections; project admins also manage model providers | Ask a project admin for the role you need |
| "Choose a project: send its id in the X-Project-Id header, or use a project API key" | `project_required` | A script called a project route without naming the project | Send `X-Project-Id`, or use a project API key |
