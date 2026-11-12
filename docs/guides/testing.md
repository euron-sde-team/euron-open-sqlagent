# Testing

Every suite below runs against real software: real PostgreSQL, MySQL and SQLite databases,
real Redis, the real API and question worker, and a deterministic model provider
(`mockai`) that speaks the OpenAI, Anthropic, Gemini and Ollama wire formats. Nothing in
the integration or browser suites mocks the database or the HTTP layer.

| Suite | Count | What it proves | Run |
| --- | --- | --- | --- |
| API unit | 184 | The SQL guard (66 parametrized cases across three dialects), the SQL describer and prompt builder, schema prompt blocks, the mock planner, every provider adapter's request and response mapping, chart suggestions, source helpers, config guards, sealing, storage, middleware, the OpenAPI drift check | `make test` |
| Web unit | 54 | The API client and error messages, the sign-in middleware, navigation per role, role checks, number and result formatting, SQLAgent-specific helpers | `make test` |
| Integration | 59 | The API in-process against Postgres 16, Redis 7, two demo database servers (PostgreSQL 16, MySQL 8.4) and SQLite files; the real worker answering questions; every acceptance criterion A1 to A12 | `make test-integration` |
| Option matrix | 4 runs | The integration suite under local and KMS sealing, local disk and S3 storage (KMS and S3 on Floci) | `make test-matrix` |
| Browser end-to-end | 6 | Sign-in, ask with SQL, table, chart and a follow-up, the guard refusing a destructive question, explain without running, schema explorer, history, audit log, templates, a viewer's read-only screens | `make e2e` |
| Browser QA sweep | every page | Every screen for every role, light and dark, desktop and phone: console errors, failed requests, horizontal overflow, broken images | `make qa` |
| Infrastructure | 3 envs | `terraform validate`, tflint, checkov (318 passed, 0 failed, 51 skipped with a reason each), and a full plan, apply, re-plan and destroy of `aws-dev` on a throwaway Floci | `make tf-validate tf-lint tf-security tf-aws-on-floci` |
| Benchmarks | 3 | SQL guard overhead, question to answer latency excluding the model, schema discovery of 500 tables | `make bench` |

The unit and integration suites together cover 90% of the API's lines and branches
(`--cov-fail-under=85` fails the run below 85%).

## Acceptance criteria and the tests that prove them

| | Criterion | Tests |
| --- | --- | --- |
| A1 | The stack installs and seeds; a user connects a demo database and asks through the API and the web app, getting a completed answer with its SQL | `test_chat.py::test_a1_*`, e2e `02-ask` |
| A2 | A connection's password is sealed, never returned, and is the credential that actually opens the database | `test_safety.py::test_a2_*` |
| A3 | Writes, DDL, multiple statements and denied functions are refused and never reach the database | `tests/unit/sql/test_guard.py` (66 cases), `test_safety.py::test_a3_*` (11 statements, plus a model that generates a write) |
| A4 | The session itself is read-only on PostgreSQL, MySQL and SQLite; a write that reaches the connection still fails at the database | `test_safety.py::test_a4_*` |
| A5 | Schema discovery lists real tables, columns, types and relationships, and the prompt is built from them; a refresh sees a new table | `test_chat.py::test_a5_*` |
| A6 | A follow-up ("and last year?") resolves against the earlier question and result | `test_chat.py::test_a6_*`, e2e `02-ask` |
| A7 | Every query, its SQL, row count and who ran it are in the append-only audit log, per connection and per user | `test_access.py::test_a7_*` |
| A8 | A query over the scan limit or the time limit is stopped and reported, on all three dialects | `test_safety.py::test_a8_*` |
| A9 | A result renders as a table and offers a chart when the shape fits | `test_chat.py::test_a9_*`, e2e `02-ask` |
| A10 | A pasted query is explained in plain words and never executed | `test_safety.py::test_a10_*`, e2e `03-guard-and-explain` |
| A11 | A member of one organization gets 404 for another's connections, conversations and audit log | `test_access.py::test_a11_*` |
| A12 | Everything above passes with no external provider; each real adapter is tested over its own wire format and is off by default | `test_providers.py::test_a12_*` (OpenAI, Anthropic, Gemini, Ollama, OpenAI-compatible, through `mockai`) |

## Running the suites

```bash
make test               # unit, no services
make test-integration   # starts Postgres, Redis, the demo databases and mockai if needed
make test-matrix        # needs Floci (started by the script)
make up && make demo    # then:
make e2e
make qa
```

`make test-integration` uses databases of its own (`sqlagent_test`, `shop_test`,
`people_test`) and a reader role of its own, so it never touches the demo data of a
running stack.

## The benchmark

`make bench` measures SQLAgent itself, with the mock provider so model time is near zero:

| Measure | Result |
| --- | --- |
| SQL guard, per query | median 354 us, p95 447 us |
| Question to answer, demo shop, warm | median 53 ms, p95 106 ms; excluding model time, median 51 ms |
| Schema discovery | 500 tables, 6,999 columns, 499 foreign keys in 0.57 s |

Measured on a laptop (Apple silicon, Docker Desktop). Your numbers will differ; the shape
should not.

## Writing tests

- A new guard rule gets a parametrized case in `tests/unit/sql/test_guard.py` for each
  dialect it applies to.
- A new endpoint gets an integration test that also checks the role it needs and that
  another tenant's id is 404.
- A new screen gets a page in `scripts/qa/qa.mjs` and, if it is a primary flow, a step in
  an e2e spec.
