# `observability` module

Logs, alarms and a dashboard:

- A KMS-encrypted log group per app: api, worker, scheduler, web, migrate.
- Metrics extracted from the apps' structured JSON logs (field `msg`), the CloudWatch side of the worker's Prometheus series (which stay inside the task):
  - `QuestionsFinished` and `QuestionsFailed`: the worker's `question finished` line (status `answered`, `refused`, `failed` or `no_answer`).
  - `QueryRefusals`: the `query refused` line the api and the worker log when the SQL guard refuses a query (anything but one read-only SELECT).
  - `QuestionsQueued`: the `queued` field of the scheduler's `question queue` line.
  - `WorkerErrors` and `SchedulerErrors`: error lines (`level` = `error`).
- Alarms to an SNS topic (optionally e-mailed): 5xx, api p95 latency, unhealthy targets, CPU and memory per service, database CPU, storage and connections, cache memory and CPU, more than `question_failure_threshold` failed questions in 5 minutes, more than `query_refusal_threshold` SQL guard refusals in 15 minutes (a spike can mean someone probing the guard), a question queue above `queue_backlog_threshold` for 15 minutes (workers down or saturated), and worker or scheduler error lines above `error_threshold` in 5 minutes.
- One dashboard with the same signals.

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| `name_prefix` | Prefix for every resource name. | `string` | required |
| `log_retention_days` | CloudWatch log retention for the app log groups. | `number` | `30` |
| `logs_kms_key_arn` | CMK for the log groups (its key policy must allow CloudWatch Logs, as the kms module's does). Null uses CloudWatch's default encryption. | `string` | `null` |
| `alarm_email` | Address subscribed to alarm notifications (confirm the e-mail AWS sends). Null: subscribe something else to the topic. | `string` | `null` |
| `alb_arn_suffix` | Load balancer ARN suffix. | `string` | required |
| `ecs_cluster_name` | ECS cluster name. | `string` | required |
| `lb_services` | Load-balanced services (service module `services`): { api = { service_name, target_group_arn_suffix }, web = { ... } }. Must contain api. | `map(object)` | required |
| `ecs_services` | Every ECS service to watch for CPU and memory (service module `service_names`): { api = "api", worker = "worker", scheduler = "scheduler", web = "web" }. | `map(string)` | required |
| `db_instance_identifier` | RDS instance identifier. | `string` | required |
| `db_max_connections` | Connection ceiling the alarm measures against. | `number` | `200` |
| `cache_replication_group_id` | ElastiCache replication group id; nodes are <id>-001, <id>-002, ... | `string` | required |
| `cache_node_count` | Nodes in the replication group (cache module num_cache_clusters). | `number` | `1` |
| `target_5xx_threshold` | 5xx responses per 5 minutes (per app, and at the load balancer) that raise an alarm. | `number` | `25` |
| `api_p95_latency_seconds` | api p95 time to first byte that raises an alarm. Asking a question waits up to 60 seconds for its answer, and generate, explain and execute call the model or the database directly, so keep it generous. | `number` | `30` |
| `question_finished_log_pattern` | CloudWatch Logs JSON filter matching the worker's `question finished` line (one per question, any status). | `string` | `"{ $.msg = \"question finished\" }"` |
| `question_failed_log_pattern` | CloudWatch Logs JSON filter matching a question that finished with status failed. | `string` | `"{ ($.msg = \"question finished\") && ($.status = \"failed\") }"` |
| `query_refused_log_pattern` | CloudWatch Logs JSON filter matching the `query refused` line the api and the worker log when the SQL guard refuses a query. | `string` | `"{ $.msg = \"query refused\" }"` |
| `question_queue_log_pattern` | CloudWatch Logs JSON filter matching the scheduler's `question queue` line (its `queued` field becomes the metric). | `string` | `"{ $.msg = \"question queue\" }"` |
| `error_log_pattern` | CloudWatch Logs JSON filter matching an error line, applied to the worker and the scheduler log groups. | `string` | `"{ $.level = \"error\" }"` |
| `question_failure_threshold` | Failed questions per 5 minutes that raise an alarm. Some failures are outside the deployment (a connected database down, an expired provider key), so this is a rate, not zero. | `number` | `10` |
| `query_refusal_threshold` | SQL guard refusals per 15 minutes (api and worker together) that raise an alarm. Models occasionally write a refused query; a spike can mean someone probing the guard. | `number` | `20` |
| `queue_backlog_threshold` | Questions waiting for a worker, sustained for 15 minutes, that raise an alarm (workers down or saturated). | `number` | `50` |
| `error_threshold` | Error lines per 5 minutes from the worker, or from the scheduler, that raise an alarm. | `number` | `5` |

## Outputs

| Name | Description |
|---|---|
| `log_group_names` | Log group per app: { api, worker, scheduler, web, migrate } (service module log_group_names). |
| `alarm_topic_arn` | SNS topic receiving every alarm. |
| `dashboard_name` | CloudWatch dashboard. |
| `metrics_namespace` | Namespace of the question, SQL guard and queue metrics extracted from the app logs. |
