# Security Policy

SQLAgent holds credentials to an organization's databases, lets a model write SQL against
them and shows people the results. We take reports seriously and respond quickly.

## Supported versions

| Version | Supported |
| ------- | --------- |
| 0.x (latest minor) | Yes |
| Older minors | No |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately through GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository ("Security" tab, "Report a vulnerability").

Please include the affected component (`apps/api`, the worker, `apps/web`,
`infra/terraform/...`) and version or commit, a description and its impact, steps to
reproduce (for a SQL guard bypass: the exact query, the database and its version), and any
suggested mitigation.

| Stage | Target |
| ----- | ------ |
| Acknowledgement | within 3 business days |
| Initial assessment and severity | within 7 business days |
| Fix or mitigation for critical and high issues | within 30 days |
| Coordinated public disclosure | after a fix is released, credited to you unless you prefer otherwise |

## Scope

In scope: the code in this repository and the infrastructure it provisions with its default
settings. We are especially interested in:

- **any way to change data in a connected database through SQLAgent**: a query that passes
  the SQL guard and writes, locks, changes session state, calls a function with side
  effects, or runs a second statement, on PostgreSQL, MySQL or SQLite; or a way around the
  read-only session,
- a query that escapes the connection's scan limit, timeout or row limit,
- explaining or validating a query causing it to be executed,
- recovering a connection password or a provider key from the API, logs or the database
  (other than by holding the sealing key),
- reading another organization's or project's connections, schemas, conversations,
  results or audit log, or using an API key beyond its project or scopes,
- requests from SQLAgent reaching instance metadata, or private addresses where the
  configuration forbids them,
- authentication or authorization bypasses, CSRF, session fixation or revocation failures,
- editing or deleting audit log entries.

Out of scope:

- **The demo seed.** `make demo` creates well-known demo accounts with the password from
  your local `.env`, on purpose.
- **The mock model provider** (`apps/api/src/mockai`), a test fixture never deployed to AWS.
- Content a model provider returns, as long as it cannot run unless the guard accepts it.
- What a model provider you configured does with the schema and result summaries SQLAgent
  sends it (see [docs/architecture/security.md](docs/architecture/security.md#what-reaches-a-model)).
- Load a valid read-only query puts on a database within its limits.
- Findings that require a compromised host, a compromised AWS account, or leaked deployment
  secrets (`SESSION_SECRET`, `API_KEY_PEPPER`, `LOCAL_MASTER_KEY`, KMS decrypt rights).

## Hardening checklist for operators

See [docs/architecture/security.md](docs/architecture/security.md#operator-checklist).
