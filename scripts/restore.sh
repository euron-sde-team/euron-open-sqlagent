#!/usr/bin/env bash
# Restore a backup made by scripts/backup.sh into the running local stack. Replaces the
# database contents and re-uploads the objects. Stops the API, worker, scheduler and web first so
# nothing writes while the database is replaced.
#   make restore BACKUP=backups/<timestamp>
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${1:?usage: scripts/restore.sh backups/<timestamp>}"
[[ "$SRC" = /* ]] || SRC="$ROOT/$SRC"
[[ -f "$SRC/sqlagent.dump" ]] || { echo "no sqlagent.dump in $SRC"; exit 1; }
COMPOSE=(docker compose --env-file "$ROOT/deploy/compose/.env" -f "$ROOT/deploy/compose/compose.yaml" -f "$ROOT/deploy/compose/compose.floci.yaml")

"${COMPOSE[@]}" stop api worker scheduler web
"${COMPOSE[@]}" exec -T postgres pg_restore -U sqlagent -d sqlagent --clean --if-exists --no-owner < "$SRC/sqlagent.dump"
docker run --rm --network sqlagent_default -v "$SRC/objects:/backup:ro" \
  -e AWS_ACCESS_KEY_ID=test -e AWS_SECRET_ACCESS_KEY=test -e AWS_DEFAULT_REGION=us-east-1 \
  amazon/aws-cli:2.22.0 --endpoint-url http://floci:4566 s3 sync /backup s3://sqlagent-local-objects --only-show-errors
"${COMPOSE[@]}" up -d --wait api worker scheduler web
echo "restored ${SRC#"$ROOT"/}"
