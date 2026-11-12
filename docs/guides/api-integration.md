# API integration

Every screen uses the same REST API: interactive docs at `http://localhost:5430/docs`, the
document in [docs/api/openapi.yaml](../api/openapi.yaml).

## Authentication

Applications use a project API key (**Settings, API keys**), sent as
`Authorization: Bearer sqa_...` or `X-API-Key: sqa_...`. A key belongs to one project; its
scopes are `read` (connections, schemas, conversations, results, usage), `query` (ask, and
generate, validate, explain and execute SQL) and `manage` (connections and templates).
`GET /api/v1/projects/current` returns the key's project.

People sign in with `POST /api/v1/auth/login` and send the returned token as a bearer
token; the dashboard uses an HttpOnly cookie and must send `X-SQA-CSRF: 1` on writes.

## Ask a question

```bash
curl -X POST "$URL/api/v1/projects/$P/chat" -H "X-API-Key: $KEY" \
  -H "content-type: application/json" \
  -d '{"connection_id": "'$C'", "question": "How many orders per status?", "wait": 30}'
```

The answer carries `status` (`answered`, `refused`, `failed`, `no_answer`, or still
`queued`/`running` if `wait` ran out), `sql`, `validated`, `explanation`, `execution`
(row count, truncated, duration, chart suggestion) and `page` (the first rows). Poll
`GET /messages/{id}?wait=10` if it was not ready. Follow up with `conversation_id` instead
of `connection_id`.

## SQL endpoints

| Endpoint | Does | Runs anything? |
| --- | --- | --- |
| `POST /sql/generate` | SQL for a question, with the guard's verdict | No |
| `POST /sql/validate` | The guard's verdict on any query (a connection or a bare dialect) | No |
| `POST /sql/explain` | A plain explanation and the syntax tree's facts | No |
| `POST /sql/execute` | Runs a query: guard, read-only session, limits, snapshot, audit | Yes, read-only |
| `GET /executions/{id}/rows?offset&limit` | A page of a stored result | No |
| `GET /executions/{id}/export.csv` | The stored result as CSV | No |

## Errors

Every error is `{"error": {"code", "type", "message", "details"}}`. A refused query is not
an HTTP error: it is a `200`/`201` whose status is `refused` with the guard's code. Rate
limits answer `429` with `Retry-After`.

## The Python SDK and CLI

`sdk/python` (`euron-sqlagent`): `SQLAgent` and `AsyncSQLAgent` clients and the
`sqlagent-cli` command, whose `ask`, `run` and `template` commands exit 1 when a query did
not run, for scheduled CI reports. See [sdk/python/README.md](../../sdk/python/README.md).
