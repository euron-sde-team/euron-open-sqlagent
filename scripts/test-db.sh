#!/usr/bin/env bash
# Make sure Postgres, Redis and the demo databases (a PostgreSQL and a MySQL) are
# reachable for the integration suite. Reuses the Compose services when the stack is up;
# otherwise starts just those.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORTS=("${SQLAGENT_PG_PORT:-5442}" "${SQLAGENT_REDIS_PORT:-5479}" "${SQLAGENT_SOURCE_PG_PORT:-5443}" "${SQLAGENT_SOURCE_MYSQL_PORT:-5406}")
SERVICES=(postgres redis source-postgres source-mysql)

ready() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

all=1
for p in "${PORTS[@]}"; do ready "$p" || all=0; done
[[ $all == 1 ]] && exit 0
"$ROOT/scripts/gen-local-env.sh" >/dev/null
docker compose --env-file "$ROOT/deploy/compose/.env" -f "$ROOT/deploy/compose/compose.yaml" \
  up -d --wait "${SERVICES[@]}"
