# 0002: Questions are queued in Postgres

**Status:** accepted

**Context.** Answering takes seconds (a model call, a query). The brief proposed Celery and
Redis.

**Decision.** The question row is the queue entry: claimed with `FOR UPDATE SKIP LOCKED`,
leased, finished with a compare-and-set, reaped by the scheduler. Pub/sub only wakes
waiters.

**Consequences.** One fewer system to run and back up; the queue is transactional with the
question it describes; scaling workers needs no coordination. Throughput is bounded by
Postgres, which is far above the rate people ask questions.
