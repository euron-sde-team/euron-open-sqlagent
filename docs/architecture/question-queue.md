# The question queue

Questions are answered by workers, not by the API request that asked them, so long model
calls and slow databases never tie up the API, a crashed worker loses nothing, and workers
scale out. The queue is the `conversation_messages` table itself
([ADR 0002](adr/0002-postgres-as-the-question-queue.md)).

| Step | Code | How |
| --- | --- | --- |
| Enqueue | `chat/service.ask` | Insert with `status = 'queued'`, publish on `sqa:queue` |
| Claim | `chat/queue.claim` | `UPDATE ... WHERE id = (SELECT id ... WHERE status = 'queued' AND available_at <= now() ORDER BY available_at LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *`, setting `running`, `lease_owner`, `lease_expires_at`, `attempts + 1` |
| Finish | `chat/queue.finish` | `UPDATE ... WHERE id = ? AND lease_owner = ? AND status = 'running'`; zero rows means the lease was lost and the result is dropped |
| Reap | `chat/queue.reap` (scheduler) | Expired leases go back to `queued` with backoff (`2^attempts` seconds, up to 30), or to `failed` with `worker_lost` after `MAX_ATTEMPTS` |
| Wait | `chat/queue.wait_for` | The API listens on `sqa:message:<id>` and polls the row, so a lost wake-up only costs a poll |

Each worker runs up to `WORKER_CONCURRENCY` questions at once as asyncio tasks. On
SIGTERM it stops claiming and gives running questions a grace period; a hard kill is safe
because the lease expires and another worker answers.

Tested by `tests/integration/test_queue.py`: a worker that dies mid-question (the question
is answered by another, exactly once, with `attempts = 2`), a question that keeps losing
its worker (failed, not looped), 18 questions across two workers (each answered once), the
scheduler's schema refresh and retention, and the per-project rate limit.
