# Threat model

STRIDE over the parts that matter most. Each row names the mitigation and where it lives.

| Threat | Example | Mitigation |
| --- | --- | --- |
| **Tampering with customer data** | A prompt-injected or hostile question makes the model write `DELETE`, a data-modifying CTE, `SELECT ... INTO`, a second statement, or `pg_sleep` | The SQL guard refuses it before any connection opens; the session is read-only in the database; a read-only login. Tests: `test_a3_*`, `test_a4_*` |
| **Tampering** | A pasted query in the explain dialog is executed | Explain parses only; `executed` is always false; no execution row. Test: `test_a10_*` |
| **Denial of service on a customer database** | A cross join over large tables | The scan limit refuses plans above `max_scan_rows`; the statement timeout cancels in the database; the row limit caps what is fetched; per-project question rate limit. Tests: `test_a8_*`, `test_questions_are_rate_limited_per_project` |
| **Information disclosure across tenants** | A member of another organization guesses ids | Every route resolves its project from the path and filters by it; unknown or foreign ids are 404. Test: `test_a11_*` |
| **Information disclosure of credentials** | Reading a connection's password or a provider key | Sealed with record-bound context; never returned; logs never carry bound parameters. Test: `test_a2_*` |
| **Information disclosure to a model provider** | Rows of a customer database sent to a hosted model | Only schema, prior SQL and result summaries are sent; sample values only when a connection opts in; the mock or a self-hosted model keeps everything local |
| **SSRF** | A connection host or provider URL pointing at instance metadata | Refused at input and again at connect time, also after DNS resolution |
| **Spoofing** | Stolen session or key | HttpOnly cookies, CSRF header, revocation, peppered key hashes, scopes, one project per key, revocation is immediate |
| **Repudiation** | "I never ran that query" | Append-only audit log with actor, SQL, status and row count, protected by a database trigger. Test: `test_a7_*` |
| **Elevation of privilege** | A viewer runs SQL | Roles checked per route (`Querier`, `Editor`, `Admin`); the web app renders no such controls for viewers. Tests: `test_project_roles`, e2e `06-viewer` |

Out of scope: a compromised host or AWS account, leaked deployment secrets, and load a
valid read-only query puts on a database within its limits.
