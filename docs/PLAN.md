# Euron Open SQLAgent: plan for 0.1.0

Source brief: `euron-open-source/briefs/14-sqlagent.md` (received 2026-11-12). The brief's
55 features across 6 areas and 7-phase roadmap are the source of truth for what SQLAgent
should eventually do; 0.1.0 scopes Phases 1 to 3 plus the parts of Phase 4 to 6 that are
genuine safety or usability requirements rather than growth features (see Scope below).
Where the brief and the program rules differ, the rules win: MIT licence (brief: Apache
2.0), the standard repo layout with domain packages under `apps/api` and Next.js (brief:
`frontend/`, `backend/`, plain React), the program's own Postgres-backed queue (brief:
Celery/Redis), Terraform for ECS on AWS (brief: Kubernetes, pushed to Roadmap).

## Purpose

SQLAgent is a self-hosted database assistant for people who are not SQL experts. A
developer, analyst, or business owner connects a database (PostgreSQL, MySQL, or SQLite in
0.1.0) and asks a question in plain English. SQLAgent discovers the schema, generates one
read-only SQL query against it, validates that the query cannot write or escape the
database, runs it against a read-only connection, and shows the result as a table or a
chart. Every query the model writes is visible before and after it runs, so nobody is ever
asked to trust an answer they cannot check.

It removes the two problems that keep non-experts away from their own data: not knowing
SQL (so the question never gets asked), and not trusting an AI tool with write access to a
production database (so the tool never gets installed). The outcome it guarantees: **a
generated query is executed only if it parses as exactly one read-only `SELECT`, with no
write, no administrative statement, and no call to a function with side effects, and the
database connection itself is opened read-only wherever the database supports it, so
validation is never the only thing standing between a question and a write.**

The name is the contract. An *agent* for SQL must (1) turn a question into a working query
against the actual connected schema, not a guess, (2) explain what it did in plain
language, (3) refuse or hold anything that is not read-only, and (4) remember the
conversation well enough to answer a follow-up like "and last year?" without the user
restating the whole question.

## Comparable products and what users expect

| Product | License | Self-hostable | Notes |
| --- | --- | --- | --- |
| Vanna AI | MIT (core) | Yes, but the core repo was archived in 2026; self-hosting now means a frozen, unpatched version | RAG over schema plus training examples; no documented AST-level write guard |
| WrenAI | Apache 2.0 for a context-engine core | The free edition is CLI/MCP only, no UI; the self-hosted platform with dashboards and RBAC is a paid Enterprise tier | Row and column security is explicitly gated behind the paid tier, not open source |
| Chat2DB | Apache 2.0 before 5.3.0, source-available with conditions from 5.3.0 | Yes | No read-only mode found; newer versions support in-place edits and DDL/DML by default |
| DataHerald | Apache 2.0 (engine) | Yes, but the engine alone has no auth; the governance layer is a separate enterprise product | No explicit read-only enforcement documented |

Expected by users of this category (table stakes): connect the common relational
databases with saved connections and automatic schema discovery; ask in plain English, see
the generated SQL, run it, see a results table; bring your own LLM key; some charting from
results; explain a pasted SQL query in plain English; query and conversation history.

**Why ours is worth starring:**

1. **Read-only is a database-enforced boundary, not a feature flag.** Every comparable
   product either leaves this undocumented, supports writes by default, or sells real
   governance as a paid add-on. SQLAgent parses every generated query into an AST
   (reusing Euron Open DataQuality's `engine/sqlguard.py` design) and opens the database
   connection itself read-only wherever the database supports it (DataQuality's
   `sources/sql.py` pattern), so a bypassed parser still cannot write.
2. **No open-core bait-and-switch.** WrenAI's free tier has no UI or RBAC; Chat2DB's
   license changed after 5.3.0. SQLAgent is MIT, fully usable from `docker compose up`,
   with nothing held back behind a paid tier, the same promise every other Euron Open
   project makes.
3. **No single point of commercial capture.** Vanna's archival shows the risk of one
   open-source maintainer's roadmap. SQLAgent supports OpenAI, Anthropic, Gemini, Ollama,
   and any OpenAI-compatible endpoint from day one, with a deterministic mock provider for
   tests, so no model vendor is load-bearing for the project's survival.

## Acceptance criteria (each one is an automated test)

| # | Criterion | Test |
| --- | --- | --- |
| A1 | `make up && make demo` installs and seeds the stack; a user connects a demo database and asks a question through the API and through the web app, getting a completed answer with its SQL | e2e + integration |
| A2 | A connection's password is sealed, never returned by the API, and is the credential actually used to open the database (the mock provider and a real test database both assert this) | integration |
| A3 | A generated query is parsed with the SQL guard before execution; a query containing INSERT, UPDATE, DELETE, DDL, multiple statements, or a denied function is refused and never reaches the database | unit + integration |
| A4 | The database connection itself is opened read-only wherever the database supports it (Postgres `default_transaction_read_only`, MySQL `SET SESSION TRANSACTION READ ONLY`, SQLite `mode=ro`); a write that somehow reaches the connection still fails at the database | integration |
| A5 | Schema discovery lists real tables, columns, types and relationships for a connected database, excluding system schemas, and the model's prompt is built from that real schema, not a guess | integration |
| A6 | A follow-up question ("and last year?") resolves using the conversation's prior question and result, without the user repeating context | integration |
| A7 | Every executed query, its generated SQL, its row count, and who ran it are recorded in an append-only audit log, visible per connection and per user | integration |
| A8 | A query that would scan more rows or run longer than its connection's configured limit is stopped and reported, not left running | integration |
| A9 | A result set renders as a table and, when the shape fits a chart (one category plus one or more numeric columns), offers a chart without the user asking for one explicitly | integration + e2e |
| A10 | Explaining a pasted SQL query (not generated by SQLAgent) returns a plain-language description of what it does, without executing it | integration |
| A11 | Tenant isolation: a member of one organization gets 404 for another organization's connections, conversations, and audit log | integration |
| A12 | Every acceptance criterion above passes with no external AI provider configured, using the deterministic mock provider; each real provider adapter is tested against a mock and is off by default | integration |

## Scope for 0.1.0

**In** (brief areas A, B, C in part, D in part, F; Phases 1 to 3 plus the safety-critical
parts of Phase 4 and 6):

- **Control plane:** organizations, projects, users, project roles (admin, editor,
  viewer), email and password sign-in, API keys, audit log (append-only).
- **Connection manager:** PostgreSQL, MySQL, SQLite connections (brief's Phase 1 list);
  sealed credentials; a connection test that reports real latency and the server version;
  per-connection row-scan and query-timeout limits; SSH tunnel support deferred to
  Roadmap (MariaDB, SQL Server, DuckDB, cloud-managed variants, and SSH tunnels are brief
  Phase 2 to 3, also Roadmap for 0.1.0).
- **Schema discovery:** tables, columns, types, primary and foreign keys, indexes, row
  counts where cheap to obtain; a schema explorer in the web app; reused from
  DataQuality's `sources/sql.py` inspection pattern across the three supported dialects.
- **Text-to-SQL engine:** schema-aware generation (joins, subqueries, CTEs, window
  functions, aggregations within the brief's Phase 2 scope), SQL explanation in plain
  language for both generated and pasted queries, dialect-aware generation, follow-up
  questions within one conversation, query templates (save and reuse a prior question).
- **SQL guard:** every generated or pasted-and-run query is parsed into an AST and
  accepted only as one read-only `SELECT`; denied functions per dialect; no multiple
  statements. Reused and extended from DataQuality's `engine/sqlguard.py`.
- **Safe execution:** read-only database connections (reused from DataQuality's
  `sources/sql.py`), row limits, statement timeouts, parameterized execution, results
  paginated.
- **Results and charts:** a results table with pagination, CSV export, and automatic chart
  suggestion (bar, line, pie) when the result shape fits one; manual chart type override.
- **Conversation history:** saved conversations per connection, replayable, with their
  generated SQL and results.
- **Audit log:** every generated query, its SQL, execution status, row count, and actor,
  append-only, visible to project admins.
- **Model providers:** `openai`, `anthropic`, `gemini`, `ollama`, `openai_compatible`
  (covers local and self-hosted inference, Euri gateway, TokenShield, SmartRouter), and a
  deterministic `mock` provider for tests and the demo. Keys sealed.
- **API and SDK:** the brief's REST surface (connections, schema, chat, SQL
  generate/validate/execute/explain, audit log), OpenAPI exported and drift tested; a
  Python SDK `euron-sqlagent` with a matching CLI.
- **Dashboard:** connections, schema explorer, chat/query workspace, results and charts,
  conversation history, audit log, settings (members, API keys).
- **Mock service** (`mockai`): a scripted model speaking the OpenAI, Anthropic, and Gemini
  wire formats, so tests, e2e, and the demo need no real provider key.

**Roadmap (not 0.1.0, from the brief's Phases 2, 4, 5, 6, and 7):** MariaDB, SQL Server,
DuckDB, Oracle, MongoDB, ClickHouse, Snowflake, BigQuery, Redshift connections; SSH
tunnels; cloud-managed database connectors; query optimization suggestions and execution
plan analysis; the specialized multi-agent architecture (query planner, performance agent,
data-quality agent as separate roles rather than one pipeline); dashboard builder from
natural language and dashboard sharing; scheduled reports and report export beyond CSV;
trend, anomaly, root-cause, and predictive analysis; business glossary; voice-to-SQL; SQL
playground diffing against production; RBAC beyond the three project roles; SSO; PII
masking in results (tracked as a real gap, candidate for 0.2.0); Kubernetes manifests.

## Architecture

```
web (Next.js 15) ──► api (FastAPI)  ──► PostgreSQL 16 (app data, connections, conversations,
                         │  ▲                           audit log, usage)
 SDK / CLI ──────────────┘  │              Redis 7 (rate limits, schema cache)
                     worker(s) ──► model providers (or mockai)
                         │      ──► connected databases (read-only): Postgres, MySQL, SQLite
                     scheduler (schema refresh, retention)
```

One Python package `sqlagent` with process roles: `sqlagent api`, `sqlagent worker`,
`sqlagent scheduler`.

**Answering a question.** The API loads the connection's cached schema (refreshed on a
schedule and on demand), builds a schema-aware prompt from the real tables and columns,
and calls the model with the conversation's prior turns for follow-up context. The model
returns a candidate SQL query and a plain-language explanation. The query is parsed by the
SQL guard; a refusal is reported to the user with the reason, never silently retried
against a different, unvalidated query. An accepted query runs against a read-only
connection to the target database, under a row limit and statement timeout, and its result
is paginated, recorded in the audit log, and offered as a table and, when it fits, a chart.

**Follow-up questions.** Each conversation keeps its prior questions, generated SQL, and a
summary of each result. A new question is answered with that history in context, so
"compare that with last year" resolves against the most recent result's metric and
timeframe, not a guess.

## Data model (main tables)

organizations, users, memberships (org role), projects, project_members (project role),
api_keys, sessions, audit_logs, model_providers (sealed key), connections (sealed
credential, kind, config, max row scan, timeout), schema_cache (per connection, refreshed
on a schedule), conversations, conversation_messages (question, generated SQL,
explanation, result summary), query_executions (SQL run, status, row count, duration,
actor), query_templates, usage_daily.

## API surface

The brief's endpoints, under `/api/v1`, scoped to a project by an API key or session, plus:
auth (login, logout, me), projects and members, connections (create, test, list, schema),
chat (ask a question, list conversations, get one), SQL (generate, validate, execute,
explain), charts (suggest a chart for a result), audit (list), usage (by connection, model,
day), system (health).

## Screens

Connections (list, add, test), schema explorer per connection, chat/query workspace (ask a
question, see generated SQL with its validated-read-only badge, see the result as a table
or chart, save as a template), conversation history, audit log, settings (members, API
keys, model providers). Sign in, empty states that teach, light and dark, phone width.

## Terraform

Modules copied from the published references: network, database (RDS PostgreSQL), cache
(ElastiCache), storage (S3, for CSV exports), kms, secrets, email (SES), ecr, service (ECS
Fargate: api, worker, scheduler, web behind an ALB), observability (CloudWatch logs,
alarms for queue backlog and SQL guard refusals). Envs `local-floci`, `aws-dev`,
`aws-prod`.

## Test plan

- **Unit:** SQL guard per dialect (reused and extended from DataQuality's test suite with
  SQLAgent-specific cases), schema-to-prompt assembly, chart-shape detection, provider
  message translation per provider (fixtures), sealing, follow-up context resolution.
- **Integration (real Postgres, Redis, mockai, and real demo MySQL/SQLite/Postgres
  sources):** every endpoint, auth and roles, tenant isolation, A1 to A12, a write attempt
  refused at both the guard and the database connection, timeout and row-limit
  enforcement, schema refresh.
- **E2E (Playwright):** sign in; connect a demo database; ask a question and see the
  validated SQL and a result; ask a follow-up; explain a pasted query; view the audit log;
  viewer has no write-adjacent controls.
- **Infrastructure:** validate, tflint, checkov, local-floci apply in `make up`,
  `make tf-aws-on-floci`.
- **QA:** Puppeteer sweep of every page, both themes, desktop and phone.
- **Bench:** question-to-answer latency excluding model time, SQL guard overhead per
  query, schema refresh time for a large schema.

## Ports

web 5410, api 5430, postgres 5442, redis 5479, floci 5466, mailpit 5425, mockai 5450, demo
MySQL 5406, tf-aws-on-floci 5496.
