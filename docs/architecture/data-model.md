# Data model

PostgreSQL 16, one Alembic revision (`migrations/versions`). Every table below the
control plane carries `project_id`; queries are always scoped by it.

| Table | Holds | Notes |
| --- | --- | --- |
| `users` | People, instance role (`admin`, `user`), password hash (argon2), lockout counters, `session_version` | Bumping `session_version` signs out every session |
| `revoked_sessions` | Signed-out session ids until they would expire | |
| `organizations`, `org_members` | Tenants and their members (`member`, `admin`, `owner`) | |
| `projects`, `project_members` | Projects in an organization; roles `viewer`, `editor`, `admin` | |
| `api_keys` | Project keys: prefix, peppered HMAC of the secret, scopes | The key itself is shown once |
| `instance_settings` | Site name, open sign-up | One row |
| `audit_log` | Every mutation, question and query: actor, action, target, details, project, organization | A trigger refuses `UPDATE` and `DELETE` |
| `model_providers` | Provider kind, base URL, model, sealed key and headers, default flag | A partial unique index allows one default per project |
| `connections` | Kind (`postgresql`, `mysql`, `sqlite`), non-secret config (JSONB), sealed password, SQLite object key, limits (`max_rows`, `max_scan_rows`, `timeout_s`), `sample_values`, last test | |
| `schema_cache` | One row per connection: discovered tables (JSONB), counts, `refreshed_at`, last error | Read through the cache by `refreshed_at` |
| `conversations` | Title, connection, chosen provider, message count, last activity | Index `(project_id, last_message_at)` |
| `conversation_messages` | The question, status, SQL, explanation, error, result summary, model and tokens, timings, and the queue columns (`attempts`, `available_at`, `lease_owner`, `lease_expires_at`) | Partial indexes for the claim (`status = 'queued'`) and the reaper (`status = 'running'`) |
| `query_executions` | Every query run or refused: SQL, status (`succeeded`, `refused`, `failed`, `timeout`, `scan_limit`), row count, truncated, duration, planner estimate, result columns, chart, snapshot key, actor | Indexes by project and time, connection and time, actor |
| `query_templates` | Saved questions, optionally with their checked SQL | |
| `usage_daily` | Questions, answers, refusals, failures, executions, rows and tokens per project, day, connection and model | Upserted with `column = column + excluded.column` |

Result rows are never stored in Postgres: `query_executions.result_key` points at a JSON
snapshot in object storage. Deleting a connection removes its executions and their
snapshots; the audit log keeps the record of every query.
