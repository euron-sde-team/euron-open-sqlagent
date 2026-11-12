# sqlagent (API, worker and scheduler)

The Python package behind Euron Open SQLAgent: the FastAPI API, the question worker, the
scheduler, and the `sqlagent` command that starts every role. One package, one image; the
command picks the role.

## Layout

```
src/sqlagent/
  core/          settings, database, Redis, sealing, storage, mail, middleware, errors
  sql/           guard.py (the SQL guard), describe.py (what a query does, from its AST),
                 prompt.py (prompts and answer parsing), service.py (generate, explain)
  connections/   sealed connections; sources.py opens databases read-only, discovers
                 schemas, estimates scans and runs queries under a row cap
  schema/        the schema cache and the schema block every prompt is built from
  executions/    safe execution: guard, read-only run, limits, result snapshots, CSV
  chat/          conversations, the Postgres question queue and the worker pipeline
  providers/     openai, anthropic, gemini, ollama, openai_compatible, and the
                 deterministic mock (mock/planner.py)
  charts/ templates/ usage/ overview/
  auth/ users/ orgs/ projects/ instance/ audit/ system/
  migrations/    Alembic
  demo/          the demo databases and make demo
  cli.py         the sqlagent command
src/mockai/      test fixture: a model provider speaking the OpenAI, Anthropic, Gemini and
                 Ollama wire formats, answering with the deterministic planner
tests/           unit/, integration/, bench/
```

Architecture: [docs/architecture/](../../docs/architecture/). Start with
[HLD.md](../../docs/architecture/HLD.md) and [LLD.md](../../docs/architecture/LLD.md).

## Commands

```bash
uv sync                                # dependencies (Python 3.12)

uv run sqlagent serve                  # the API on $PORT (8080)
uv run sqlagent worker                 # the question worker
uv run sqlagent scheduler              # periodic tasks: lease reaper, schema refresh, retention
uv run sqlagent migrate                # apply migrations
uv run sqlagent revision -m "..."      # autogenerate a migration from the models
uv run sqlagent create-admin --email you@example.com
uv run sqlagent seed-demo              # the demo (expects the Compose stack)
uv run sqlagent openapi                # print the OpenAPI document as YAML
```

Configuration is environment only: [docs/guides/configuration.md](../../docs/guides/configuration.md).

## Tests

```bash
uv run pytest tests/unit                       # no database, no network
uv run pytest tests/unit tests/integration     # needs Postgres, Redis and the demo databases
uv run python -m tests.bench.bench_sqlagent    # guard overhead, question latency, schema refresh
```

From the repository root, `make test`, `make test-integration`, `make test-matrix` and
`make bench` wrap these. Details: [docs/guides/testing.md](../../docs/guides/testing.md).

## Licence

MIT, see [LICENSE](../../LICENSE).
