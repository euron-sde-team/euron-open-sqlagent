# Low-level design

Where things live in the code and how the pieces call each other. Start with
[HLD.md](HLD.md) for the big picture.

## Package layout (`apps/api/src/sqlagent`)

| Package | Owns |
| --- | --- |
| `core/` | Settings and the production guard (`config.py`), the async engine and `Base` (`db.py`), the key-value cache with Redis or memory backends (`kv.py`), pub/sub (`pubsub.py`), sealing (`sealing.py`), object storage (`storage.py`), mail (`mail.py`), middleware, errors, logging, periodic task registry (`tasks.py`), outbound address checks (`net.py`) |
| `auth/`, `users/`, `orgs/`, `projects/`, `instance/` | The control plane: sessions, users, organizations, projects with roles (viewer, editor, admin), API keys with scopes (read, query, manage), instance settings. `projects/access.py` resolves every request into a `Principal` |
| `connections/` | Sealed connections (`models.py`, `service.py`) and `sources.py`: opening a database read-only, discovery, scan estimates, row-capped execution |
| `schema/` | The schema cache (`service.py`) and the schema block of the prompt (`prompt.py`: render, relevance ranking, parse back) |
| `sql/` | `guard.py` (the SQL guard), `describe.py` (facts and a description from the syntax tree), `prompt.py` (messages and answer parsing), `service.py` (generate, validate, explain), `router.py` |
| `executions/` | Safe execution (`service.execute`), result snapshots, pages, CSV |
| `chat/` | Conversations and questions (`models.py`, `service.py`), the queue (`queue.py`), the worker pipeline (`engine.py`), periodic tasks (`tasks.py`) |
| `providers/` | Provider rows and sealed keys (`service.py`), adapters per wire format (`adapters/`), the retrying gateway, and `mock/` (the deterministic planner and responder) |
| `charts/`, `templates/`, `usage/`, `overview/`, `audit/`, `system/` | Chart suggestion, saved questions, daily rollups, the project landing page, the append-only audit log, health and metrics |
| `demo/` | The demo databases and `make demo` |
| `src/mockai/` | A model provider service speaking four wire formats, answering with `providers/mock/responder.py` |

Routers parse and shape; services hold the rules; every project-scoped query filters on the
project id taken from the `Principal`, so another tenant's ids are simply not found.

## Request path of a question

```
chat/router.ask
  -> chat/service.ask             rate limit, conversation, message (queued), audit, notify
  -> chat/queue.wait_for          pub/sub on sqa:message:<id>, plus a poll
worker.serve -> chat/queue.claim  FOR UPDATE SKIP LOCKED, lease
  -> chat/engine.answer
       history()                  prior answered turns of the conversation
       sql/service.generate       schema/service.ensure, sql/prompt, providers/gateway
       executions/service.execute guard.check, connections/service.run_sync(
                                    sources.estimate_scan, sources.run_query),
                                  storage.put(snapshot), audit, usage
  -> chat/queue.finish            compare-and-set on lease_owner
  -> pubsub.publish               wakes the waiting request
```

`/sql/execute` calls `executions/service.execute` directly from the API; `/sql/generate` and
`/sql/explain` call `sql/service` directly. Nothing else reaches a customer database.

## Threads and timeouts

Customer databases are reached with synchronous drivers (psycopg, PyMySQL, sqlite3) in a
worker thread (`asyncio.to_thread`), one connection per call, no pool, closed afterwards.
The statement timeout is set on the session and enforced by the database; the async side
only stops waiting `timeout + 30` seconds later in case the network hangs.

## Frontend (`apps/web/src`)

`app/` holds thin routes; `features/<domain>/` holds screens and TanStack Query hooks
(`api.ts`) for ask, connections, history, templates, overview, providers, projects, audit,
users and settings. API types are generated from `docs/api/openapi.yaml`
(`pnpm gen:api`). Charts use Recharts with the theme's series tokens.
