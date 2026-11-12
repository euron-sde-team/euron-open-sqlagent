## What and why

<!-- One paragraph: the problem, and how this change solves it. Link the issue. -->

## How it was verified

- [ ] `make lint typecheck test`
- [ ] `make test-integration` (if the API, the question worker, a database driver, a cache or database code changed)
- [ ] `make e2e` (if a user flow or infrastructure changed)
- [ ] `make tf-validate tf-lint tf-security tf-aws-on-floci` (if Terraform changed)

## Checklist

- [ ] Docs updated (README, `docs/`, configuration reference) for any behavior or config change
- [ ] New Alembic revision instead of editing an applied one
- [ ] Every query still passes the SQL guard before it runs, connections stay read-only in the database itself, and connection passwords and provider keys stay sealed (never logged, never returned by the API)
- [ ] A change to the SQL guard comes with tests that prove the new refusals and acceptances on every dialect
- [ ] No new place where rows of a connected database reach a model provider (sample values only where the connection allows them)
- [ ] The mock provider still answers the demo and test questions deterministically
- [ ] `make openapi` run if the API changed
- [ ] No secrets, account ids, real hostnames or em/en dashes (`make sanitize` is clean)
- [ ] Security-relevant change? Described the threat and mitigation above
