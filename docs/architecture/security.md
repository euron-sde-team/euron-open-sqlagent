# Security

SQLAgent holds credentials to an organization's databases, lets a model write SQL against
them and shows people the results. Its security rests on a few properties, each enforced in
one place and each covered by a test.

## Read-only, twice over

1. **The SQL guard** parses every query into a syntax tree in the connection's dialect and
   accepts only one read-only `SELECT` ([sql-guard.md](sql-guard.md)). A refused query
   never reaches a database.
2. **The session itself is read-only**, enforced by the database
   (`connections/sources.py`): PostgreSQL connections set
   `default_transaction_read_only=on`; MySQL sessions run
   `SET SESSION TRANSACTION READ ONLY`; SQLite files are opened with `mode=ro` and
   `PRAGMA query_only`. Every transaction is rolled back and every connection closed. A
   write that somehow passed the guard fails at the database:
   `test_a4_a_write_that_reaches_the_connection_still_fails_at_the_database` sends writes
   straight down the connection, logged in as a user with write rights, on all three.
3. **The login you give it** is the third layer: use one that can only `SELECT` (the demo
   does, as `sqlagent_reader`).

## Limits a query cannot escape

Per connection, capped by instance ceilings: the **scan limit** (the database's own planner
estimate from `EXPLAIN`, which runs nothing, is checked before the query starts), the
**statement timeout** (set on the session, enforced by the database), and the **row limit**
(rows past it are never fetched; the result says it was cut).

## Credentials

Connection passwords and provider keys are sealed before storage, with AES-256-GCM under a
local master key or AWS KMS (`KEY_MODE`), and the record's id as additional data or
encryption context, so a sealed value copied to another row does not open. The API returns
only `has_password` / `has_api_key`. The sealed password is the credential that opens the
database (`test_a2_...` proves it by storing a wrong one).

## Tenants and roles

Every project-scoped route resolves a `Principal` (person or API key) for the project in
its path; organization membership and project roles decide access, and another tenant's
project, connection, conversation or execution answers 404, never 403
(`test_a11_another_organization_gets_404_for_everything_of_ours`). Roles: viewers read,
editors ask and run SQL and manage connections, admins manage members, keys, providers and
read the audit log. API keys are peppered HMAC hashes with scopes `read`, `query`,
`manage`, bound to one project.

## Sessions and requests

HttpOnly session cookies with a required `X-SQA-CSRF: 1` header on cookie-authenticated
mutations, server-side revocation, a session version bumped on password change, sign-in
rate limits and lockout, body size limits (larger only for signed-in SQLite uploads),
security headers and a strict Content-Security-Policy in the web app.

## Outbound connections

Database hosts and provider URLs are checked when typed and again as they resolve at
connect time: link-local and instance metadata addresses are always refused; private
addresses can be refused with `SOURCE_ALLOW_PRIVATE=false` and `PROVIDER_ALLOW_PRIVATE=false`.

## What reaches a model

The schema (names and types), the conversation's prior questions with their SQL and a short
summary of each result (row count, columns, first rows), and, only when a connection turns
`sample_values` on, the distinct values of short text columns. Use the mock provider or a
self-hosted model if none of that may leave the network. PII masking in results is on the
roadmap.

## Audit

Every question, every query run or refused (SQL, status, row count, actor), and every
change is written to `audit_log` in the same transaction as the change. A database trigger
refuses `UPDATE` and `DELETE` on it.

## Operator checklist

- Production boot guards refuse demo secrets, local storage, mail to the log and cookies
  without `Secure`; set them properly rather than relaxing `ENVIRONMENT`.
- Give SQLAgent read-only logins, and restrict `source_cidrs` in Terraform to your
  database networks.
- Use `KEY_MODE=kms` on AWS.
- Leave `sample_values` off on databases with personal data unless the provider is yours.
- Review the audit log for `query.refused` spikes (the CloudWatch alarm does this).
