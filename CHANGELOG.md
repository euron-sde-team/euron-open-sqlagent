# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[semantic versioning](https://semver.org/).

## [0.1.0] - 2026-11-12

First release.

### Added

- **Connections** to PostgreSQL, MySQL and SQLite (uploaded file), with sealed passwords
  (AES-GCM or AWS KMS), a connection test that reports the real round trip, the server
  version and a confirmed read-only session, and per-connection row, scan and timeout
  limits.
- **Schema discovery**: tables, views, columns, types, primary and foreign keys, indexes,
  row counts and, when allowed, example values; cached and refreshed on a schedule and on
  demand; a schema explorer in the web app.
- **Text to SQL**: schema-aware prompts within a budget, the conversation's prior turns
  for follow-up questions, dialect-aware generation, plain-language explanations of
  generated and pasted queries, query templates.
- **The SQL guard**: every query parsed per dialect and accepted only as one read-only
  `SELECT`; writes, administrative statements, data-modifying CTEs, `SELECT INTO`, locks,
  multiple statements, side-effecting functions and table functions refused with a reason.
- **Safe execution** on read-only sessions (PostgreSQL, MySQL, SQLite), with the planner's
  scan estimate checked before running, the statement timeout enforced by the database,
  the row limit applied while fetching, results snapshotted to object storage, paged and
  exported as CSV.
- **Charts** suggested from a result's shape (bar, line, pie) with a manual override.
- **Conversations** replayable with their SQL and results; the question queue in
  PostgreSQL with leases, recovery and per-project rate limits.
- **Audit log**, append-only and protected by a database trigger, with every question and
  every query run or refused, filterable by connection and person.
- **Model providers**: OpenAI, Anthropic, Gemini, Ollama, any OpenAI-compatible endpoint,
  and a deterministic mock; keys sealed; a default per project.
- **Control plane**: organizations, projects, roles (viewer, editor, admin), email and
  password sign-in, API keys with scopes, usage rollups, instance administration.
- **Python SDK and CLI** (`euron-sqlagent`, `sqlagent-cli`).
- **Web app**: overview, ask workspace, connections and schema explorer, history,
  templates, audit log, settings; light and dark, phone width.
- **Infrastructure**: Docker Compose with Floci, Terraform modules and environments for AWS
  (ECS Fargate api, worker, scheduler and web behind an ALB; RDS; ElastiCache; S3; KMS;
  Secrets Manager; SES; ECR; CloudWatch alarms for the queue backlog and guard refusals).
