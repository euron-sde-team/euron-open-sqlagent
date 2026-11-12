# Quickstart (local)

Everything runs in Docker: no AWS account, no model key, nothing installed on the host
except Docker (and uv and pnpm if you want to run the tests outside containers).

```bash
git clone https://github.com/euron-sde-team/euron-open-sqlagent.git
cd euron-open-sqlagent
make up      # builds the images, starts the stack, applies Terraform to the local AWS emulator
make demo    # demo databases, people, connections, conversations; prints the logins
```

Open http://localhost:5410 and sign in as `maya.chen@example.com` (admin),
`arjun.mehta@example.com` (editor) or `sofia.lopez@example.com` (viewer) with the password
`make demo` prints (it is also `SQLAGENT_DEMO_PASSWORD` in `deploy/compose/.env`).

## What `make up` starts

| Service | Port | What |
| --- | --- | --- |
| web | 5410 | The dashboard |
| api | 5430 | The API, with interactive docs at `/docs` |
| worker, scheduler | | Answer questions; refresh schemas, reap leases, apply retention |
| postgres | 5442 | SQLAgent's own database |
| redis | 5479 | Rate limits and caches |
| floci | 5466 | S3, KMS and Secrets Manager, provisioned by `infra/terraform/envs/local-floci` |
| mailpit | 5425 | Catches mail (member notices) |
| mock-ai | 5450 | A deterministic model provider speaking four wire formats |
| source-postgres | 5443 | Demo database `shop` |
| source-mysql | 5406 | Demo database `people` |

Ports can be moved in `deploy/compose/.env` (`SQLAGENT_WEB_PORT` and friends).

## First questions

1. Open **Retail analytics**, then **Ask**.
2. Pick **Shop (PostgreSQL)** and ask "How many orders per status?". You see the SQL, the
   *Validated read-only* badge, a plain explanation, the result and a pie chart.
3. Follow up with "only cancelled ones", then "break it down by channel".
4. Ask "Delete all cancelled orders": the SQL guard refuses it and nothing runs.
5. Use **Explain SQL** on any query you paste: it is described, never executed.

## Your own database

**Connections**, **Add a database**: host, port, database, a read-only login; **Test
connection** shows the round trip, the server version and that the session is read-only.
A database on your laptop is reachable from the containers as `host.docker.internal`.
Then add a model provider under **Settings, Model providers** if the built-in mock is not
enough: OpenAI, Anthropic, Gemini, Ollama or any OpenAI-compatible endpoint.

## Stop and reset

```bash
make down    # stop and delete every container and volume of this stack
make up && make demo
```
