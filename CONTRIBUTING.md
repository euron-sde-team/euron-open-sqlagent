# Contributing

Thanks for helping improve Euron Open SQLAgent. This guide covers the workflow, the bar a
change has to clear, and the conventions the codebase follows.

## Ground rules

- **Open an issue first** for anything larger than a bug fix or a docs tweak, so we can
  agree on the approach before you invest time.
- **One concern per pull request.** A refactor and a feature are two PRs.
- **Security issues go through private reporting**, never a public issue. That includes any
  way to make SQLAgent write to a connected database, read another tenant's data, or recover
  a sealed credential. See [SECURITY.md](SECURITY.md).
- By contributing you agree your work is released under the [MIT License](LICENSE).

## Development setup

Requirements: Docker, Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22 and
pnpm (`corepack enable`).

```bash
make up          # the whole stack, with the local AWS emulator provisioned by Terraform
make demo        # demo databases, people, connections and conversations
make test        # unit tests (API and web)
```

[docs/guides/quickstart-local.md](docs/guides/quickstart-local.md) walks through the local
stack, and [docs/architecture/LLD.md](docs/architecture/LLD.md) maps the code.

## Before you open a pull request

```bash
make lint typecheck test
make test-integration                  # the API against real Postgres, Redis and the demo databases
make test-matrix                       # when you touched sealing, storage or anything AWS
make e2e                               # when you touched a web flow or infrastructure
make tf-validate tf-lint tf-security   # when you touched infra/terraform
make tf-aws-on-floci                   # same: apply and destroy aws-dev against Floci
make openapi                           # when you changed an endpoint or a schema
make sanitize                          # no credentials, account ids or dashes
```

## Conventions

**Package by domain.** `apps/api/src/sqlagent/<domain>/` owns its `router.py` (HTTP only),
`schemas.py` (the public contract), `service.py` (rules) and `models.py`. A domain calls
another domain's service, never its tables directly.

**Nothing reaches a database except through `executions/service.execute`.** It runs the SQL
guard, opens the connection read-only, checks the scan limit, applies the row limit and
timeout, and records the execution and the audit entry. A change to `sql/guard.py` or
`connections/sources.py` needs tests that prove the new refusals and acceptances on every
dialect, and a change that weakens either lock will not be merged.

**The mock provider stays deterministic.** `providers/mock/planner.py` answers the demo and
the test suites; extend its tests in `tests/unit/providers/test_planner.py` when you
change it.

**Secrets are sealed and never returned.** Anything that grants access goes through the
sealer with a context bound to its row, and the API shows at most whether one is stored.

**Caches are documented.** A new cache layer goes in the caching table of
[docs/architecture/HLD.md](docs/architecture/HLD.md) with its key, TTL and invalidation,
and its invalidation is tested.

**Configuration is validated.** A new setting goes in `core/config.py`, is documented in
[docs/guides/configuration.md](docs/guides/configuration.md), and security-relevant ones are
enforced by `guard()` at boot.

**Database changes are new migrations.** Change the models, then
`uv run sqlagent revision -m "what changed"` against a local database and review it. Never
edit an applied one.

**The web app uses the generated client.** After an API change, `make openapi` and
`pnpm gen:api` in `apps/web`; never hand-write API types.

**Style.** ruff and mypy `--strict` for Python; ESLint and TypeScript strict for the web.
No em dashes or en dashes anywhere (the sanitization check enforces it). Comments explain
why, not what.

## Commit messages

Imperative mood with an optional scope: `guard: refuse data-modifying CTEs on MySQL`,
`web: show the planner estimate on a scan limit refusal`.

## Architecture decisions

Significant decisions are recorded in [docs/architecture/adr/](docs/architecture/adr/). If
your change reverses or extends one, add a new ADR rather than editing the old one.
