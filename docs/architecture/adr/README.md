# Architecture decisions

| # | Decision |
| --- | --- |
| [0001](0001-two-locks-for-read-only.md) | Read-only is enforced twice: by the SQL guard and by the database session |
| [0002](0002-postgres-as-the-question-queue.md) | Questions are queued in Postgres, not in a separate broker |
| [0003](0003-sqlglot-for-the-guard.md) | The guard parses with sqlglot, per dialect, instead of matching keywords |
| [0004](0004-a-deterministic-mock-provider.md) | A deterministic mock provider makes every test and the demo independent of any model vendor |
| [0005](0005-result-snapshots-in-object-storage.md) | Results are snapshots in object storage, not rows in Postgres |
| [0006](0006-scan-limit-from-the-planner.md) | The scan limit uses the database planner's own estimate |
| [0007](0007-mit-licence.md) | MIT licence |
| [0008](0008-nextjs-frontend.md) | Next.js for the web app |
| [0009](0009-one-package-three-roles.md) | One Python package and image for the API, the worker and the scheduler |
