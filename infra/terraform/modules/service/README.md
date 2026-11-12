# `service` module

The application plane on ECS Fargate behind one Application Load Balancer:

| App | Role | Exposure |
|---|---|---|
| `api` | `sqlagent serve`: the API (`/api/*`), probes, docs, connection tests, schema discovery, SQLite uploads, SQL generate, explain and execute | ALB on `hostname` (port `api_port`, 8080, `/healthz`); Cloud Map for the web app |
| `worker` | `sqlagent worker`: claims queued questions from Postgres (`FOR UPDATE SKIP LOCKED`), asks the model provider for one SQL query, runs it read-only on the connected database, writes the result snapshot to S3 | none: its `/metrics` (9464) stays inside the task |
| `scheduler` | `sqlagent scheduler`: lease reaper, schema refresh, retention (deletes old result snapshots from S3) | none, no metrics port; always exactly one task |
| `web` | the Next.js app (every other path) | ALB (port `web_port`, 3000) |
| `migrate` | one-off task for `migrate`, `create-admin`, `seed-demo` | none |

`api`, `worker`, `scheduler` and `migrate` run the same image (the `sqlagent` CLI is its entrypoint); `web` has its own. SQLite databases are copied from S3 under `WORK_DIR` (the writable `/tmp`) before they are queried, so the api, worker and scheduler have ephemeral storage inputs (`worker_ephemeral_gib` is 30 GiB by default, the others use the Fargate default of 20 GiB).

The api (connection tests, schema discovery), the worker (queries) and the scheduler (schema refresh) connect out to the databases people connect on `source_ports` (PostgreSQL 5432, MySQL 3306) to `source_cidrs`. The default is anywhere; restrict `source_cidrs` to your database networks wherever you can. The api and worker call model providers over HTTPS; `ai_egress` opens another port for a self-hosted model.

The scheduler runs as one task and is deployed with minimum healthy 0 and maximum 100 percent, so two schedulers never run side by side. Workers roll like any other service: several are safe because questions are claimed with `SKIP LOCKED` and leased.

Every app: its own security group (ingress only from the ALB or named callers), its own execution and task roles (only the api, worker, scheduler and migrate touch S3 and KMS; only the api may send mail through SES, with `send_mail`), read-only root filesystem, ARM64, no public IP, deployment circuit breaker with rollback. WAF with AWS managed rules; the body rules that mistake SQL text and uploaded SQLite files for attacks only count.

## Inputs

| Name | Description | Type | Default |
|---|---|---|---|
| `name_prefix` | Deployment prefix, e.g. "sqlagent-prod". At most 24 characters, so target group names stay unique within AWS's 32-character limit. | `string` | required |
| `vpc_id` | VPC of the load balancer and the tasks. | `string` | required |
| `public_subnet_ids` | Public subnets for the load balancer. | `list(string)` | required |
| `private_subnet_ids` | Private subnets the tasks run in. | `list(string)` | required |
| `hostname` | Public host name of the web app and API, e.g. sqlagent.example.com. The certificate must cover it. | `string` | required |
| `certificate_arn` | ACM certificate (same region) for the HTTPS listener, covering hostname. | `string` | required |
| `route53_zone_id` | Hosted zone to create the hostname alias record in. Null: point DNS at alb_dns_name yourself. | `string` | `null` |
| `api_image` | Full api image reference (also runs the worker, the scheduler and migrate), e.g. <registry>/sqlagent-prod/api:<tag>. | `string` | required |
| `web_image` | Full web image reference, e.g. <registry>/sqlagent-prod/web:<tag>. | `string` | required |
| `api_port` | Port the api container listens on (passed to `sqlagent serve --port`). | `number` | `8080` |
| `web_port` | Port the web container listens on (PORT). | `number` | `3000` |
| `environment` | Plain environment for api, worker, scheduler and migrate (PUBLIC_URL and OBJECTS_BUCKET are set by the module). Never secrets. | `map(string)` | `{}` |
| `web_environment` | Plain environment for web (PORT, HOSTNAME and API_INTERNAL_URL are set by the module). Never secrets. | `map(string)` | `{}` |
| `secrets` | Secrets injected into api, worker, scheduler and migrate: [{ name, valueFrom = "<secret arn>:<json key>::" }] (secrets module ecs_secrets). | `list(object)` | `[]` |
| `kms_key_arn` | CMK that seals connection passwords and model provider API keys (encryption context sqlagent:record), encrypts the objects bucket and the injected secrets. | `string` | required |
| `objects_bucket_arn` | Objects bucket (storage module bucket_arn). | `string` | required |
| `objects_bucket_name` | Objects bucket name (storage module bucket_name), passed as OBJECTS_BUCKET. | `string` | required |
| `db_security_group_id` | Database security group; api, worker, scheduler and migrate get ingress on it. | `string` | required |
| `db_port` | Database port. | `number` | `5432` |
| `cache_security_group_id` | Cache security group; api, worker, scheduler and migrate get ingress on it. | `string` | required |
| `cache_port` | Cache port. | `number` | `6379` |
| `log_group_names` | CloudWatch log group per app: { api, worker, scheduler, web, migrate } (observability module log_group_names). | `map(string)` | required |
| `logs_kms_key_arn` | CMK for the WAF log group. Null uses CloudWatch's default encryption. | `string` | `null` |
| `cpu_architecture` | ARM64 (Graviton, cheaper) or X86_64. Images must be built for it. | `string` | `"ARM64"` |
| `container_insights` | ECS Container Insights: enabled, enhanced or disabled. | `string` | `"enabled"` |
| `api_cpu` | Fargate CPU units per api task. | `number` | `1024` |
| `api_memory` | Fargate memory (MiB) per api task. | `number` | `2048` |
| `api_min_count` | Minimum (and initial) api task count. | `number` | `2` |
| `api_max_count` | Maximum api task count under autoscaling. Equal to api_min_count disables scaling. | `number` | `6` |
| `api_ephemeral_gib` | Fargate ephemeral storage (GiB, 21 to 200) per api task. SQLite uploads and cached SQLite copies (connection tests, schema discovery) live under WORK_DIR there. Null: the Fargate default of 20 GiB. | `number` | `null` |
| `worker_cpu` | Fargate CPU units per worker task. | `number` | `512` |
| `worker_memory` | Fargate memory (MiB) per worker task. Result pages up to the row ceiling are held in memory while a query runs. | `number` | `1024` |
| `worker_ephemeral_gib` | Fargate ephemeral storage (GiB, 21 to 200) per worker task. SQLite databases are copied from S3 under WORK_DIR before they are queried. Null: the Fargate default of 20 GiB. | `number` | `30` |
| `worker_count` | Question worker task count. Several are safe (questions are claimed with FOR UPDATE SKIP LOCKED and leased); not autoscaled, raise it or WORKER_CONCURRENCY when the queue backs up. | `number` | `1` |
| `scheduler_cpu` | Fargate CPU units for the scheduler (always exactly one task). | `number` | `256` |
| `scheduler_memory` | Fargate memory (MiB) for the scheduler. | `number` | `512` |
| `scheduler_ephemeral_gib` | Fargate ephemeral storage (GiB, 21 to 200) for the scheduler, which copies SQLite databases under WORK_DIR to refresh their schemas. Null: the Fargate default of 20 GiB. | `number` | `null` |
| `web_cpu` | Fargate CPU units per web task. | `number` | `512` |
| `web_memory` | Fargate memory (MiB) per web task. | `number` | `1024` |
| `web_min_count` | Minimum (and initial) web task count. | `number` | `1` |
| `web_max_count` | Maximum web task count under autoscaling. | `number` | `3` |
| `cpu_target_percent` | Average CPU the autoscaler aims for (api and web). | `number` | `60` |
| `idle_timeout` | Load balancer idle timeout in seconds. Asking a question waits up to 60 seconds for its answer; this also bounds how long a stalled SQLite upload is kept. | `number` | `120` |
| `deletion_protection` | Block accidental deletion of the load balancer. | `bool` | `true` |
| `access_logs_bucket` | Existing bucket for load balancer access logs (needs the ELB log-delivery bucket policy). Null disables. | `string` | `null` |
| `metrics_allowed_cidrs` | Source CIDRs allowed to read /metrics through the load balancer. Empty: /metrics answers 404 at the edge. | `list(string)` | `[]` |
| `enable_waf` | Attach a WAF web ACL (managed rule sets plus a per-IP flood guard) to the load balancer. | `bool` | `true` |
| `waf_rate_limit_per_5min` | Requests per source IP per 5 minutes before WAF blocks. Keep it high: SDK backends often sit behind one NAT address. | `number` | `20000` |
| `waf_log_retention_days` | WAF log retention. | `number` | `30` |
| `source_cidrs` | Networks of the databases people connect, which the api (connection tests, schema discovery), the worker (queries) and the scheduler (schema refresh) may reach on source_ports. Default: anywhere. Restrict it to your database networks wherever you can. | `list(string)` | `["0.0.0.0/0"]` |
| `source_ports` | Ports of the databases people connect (PostgreSQL 5432 and MySQL 3306 by default). HTTPS 443 is always open. | `list(number)` | `[5432, 3306]` |
| `ai_egress` | Extra egress from the api and worker tasks for a self-hosted model provider not on HTTPS 443, as { cidr, port } pairs (for example Ollama or vLLM inside the VPC). Empty: HTTPS only. | `list(object)` | `[]` |
| `send_mail` | Attach mail_policy_json to the api task role (project notice mail through SES). The worker and scheduler send no mail. | `bool` | `false` |
| `mail_policy_json` | IAM policy for sending notice mail (email module send_policy_json), with send_mail. | `string` | `null` |

## Outputs

| Name | Description |
|---|---|
| `cluster_name` | ECS cluster name. |
| `cluster_arn` | ECS cluster ARN. |
| `url` | Public URL of the web app and API. |
| `internal_urls` | Private service URLs through Cloud Map: { api }. The web app uses it as API_INTERNAL_URL. |
| `alb_dns_name` | Load balancer DNS name (CNAME target for the host name when the zone is not in Route53). |
| `alb_arn_suffix` | Load balancer ARN suffix, for CloudWatch metrics. |
| `services` | Load-balanced services: { api, web } => { service_name, target_group_arn_suffix }. |
| `service_names` | Every ECS service name (api, worker, scheduler, web). |
| `security_group_ids` | Task security group per app. |
| `task_role_arns` | Task role per app. |
| `run_task` | Parameters for one-off tasks: `sqlagent migrate` (task_definition, the default), or `create-admin` and `seed-demo` as command overrides on the same definition. |
| `namespace_id` | Cloud Map private DNS namespace (api.<name_prefix>.internal resolves through it). |
