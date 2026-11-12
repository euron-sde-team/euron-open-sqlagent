variable "name_prefix" {
  description = "Deployment prefix, e.g. \"sqlagent-prod\". At most 24 characters, so target group names stay unique within AWS's 32-character limit."
  type        = string
  validation {
    condition     = length(var.name_prefix) <= 24
    error_message = "name_prefix must be at most 24 characters."
  }
}

variable "vpc_id" {
  description = "VPC of the load balancer and the tasks."
  type        = string
}

variable "public_subnet_ids" {
  description = "Public subnets for the load balancer."
  type        = list(string)
}

variable "private_subnet_ids" {
  description = "Private subnets the tasks run in."
  type        = list(string)
}

variable "hostname" {
  description = "Public host name of the web app and API, e.g. sqlagent.example.com. The certificate must cover it."
  type        = string
}

variable "certificate_arn" {
  description = "ACM certificate (same region) for the HTTPS listener, covering hostname."
  type        = string
}

variable "route53_zone_id" {
  description = "Hosted zone to create the hostname alias record in. Null: point DNS at alb_dns_name yourself."
  type        = string
  default     = null
}

variable "api_image" {
  description = "Full api image reference (also runs the worker, the scheduler and migrate), e.g. <registry>/sqlagent-prod/api:<tag>."
  type        = string
}

variable "web_image" {
  description = "Full web image reference, e.g. <registry>/sqlagent-prod/web:<tag>."
  type        = string
}

variable "api_port" {
  description = "Port the api container listens on (passed to `sqlagent serve --port`)."
  type        = number
  default     = 8080
}

variable "web_port" {
  description = "Port the web container listens on (PORT)."
  type        = number
  default     = 3000
}

variable "environment" {
  description = "Plain environment for api, worker, scheduler and migrate (PUBLIC_URL and OBJECTS_BUCKET are set by the module). Never secrets."
  type        = map(string)
  default     = {}
}

variable "web_environment" {
  description = "Plain environment for web (PORT, HOSTNAME and API_INTERNAL_URL are set by the module). Never secrets."
  type        = map(string)
  default     = {}
}

variable "secrets" {
  description = "Secrets injected into api, worker, scheduler and migrate: [{ name, valueFrom = \"<secret arn>:<json key>::\" }] (secrets module ecs_secrets)."
  type        = list(object({ name = string, valueFrom = string }))
  default     = []
}

variable "kms_key_arn" {
  description = "CMK that seals connection passwords and model provider API keys (encryption context sqlagent:record), encrypts the objects bucket and the injected secrets."
  type        = string
}

variable "objects_bucket_arn" {
  description = "Objects bucket (storage module bucket_arn)."
  type        = string
}

variable "objects_bucket_name" {
  description = "Objects bucket name (storage module bucket_name), passed as OBJECTS_BUCKET."
  type        = string
}

variable "db_security_group_id" {
  description = "Database security group; api, worker, scheduler and migrate get ingress on it."
  type        = string
}

variable "db_port" {
  description = "Database port."
  type        = number
  default     = 5432
}

variable "cache_security_group_id" {
  description = "Cache security group; api, worker, scheduler and migrate get ingress on it."
  type        = string
}

variable "cache_port" {
  description = "Cache port."
  type        = number
  default     = 6379
}

variable "log_group_names" {
  description = "CloudWatch log group per app: { api, worker, scheduler, web, migrate } (observability module log_group_names)."
  type        = map(string)
  validation {
    condition     = alltrue([for k in ["api", "worker", "scheduler", "web", "migrate"] : contains(keys(var.log_group_names), k)])
    error_message = "log_group_names needs api, worker, scheduler, web and migrate."
  }
}

variable "logs_kms_key_arn" {
  description = "CMK for the WAF log group. Null uses CloudWatch's default encryption."
  type        = string
  default     = null
}

variable "cpu_architecture" {
  description = "ARM64 (Graviton, cheaper) or X86_64. Images must be built for it."
  type        = string
  default     = "ARM64"
}

variable "container_insights" {
  description = "ECS Container Insights: enabled, enhanced or disabled."
  type        = string
  default     = "enabled"
}

variable "api_cpu" {
  description = "Fargate CPU units per api task."
  type        = number
  default     = 1024
}

variable "api_memory" {
  description = "Fargate memory (MiB) per api task."
  type        = number
  default     = 2048
}

variable "api_min_count" {
  description = "Minimum (and initial) api task count."
  type        = number
  default     = 2
}

variable "api_max_count" {
  description = "Maximum api task count under autoscaling. Equal to api_min_count disables scaling."
  type        = number
  default     = 6
}

variable "api_ephemeral_gib" {
  description = "Fargate ephemeral storage (GiB, 21 to 200) per api task. SQLite uploads and cached SQLite copies (connection tests, schema discovery) live under WORK_DIR there. Null: the Fargate default of 20 GiB."
  type        = number
  default     = null
  validation {
    condition     = var.api_ephemeral_gib == null ? true : (var.api_ephemeral_gib >= 21 && var.api_ephemeral_gib <= 200)
    error_message = "api_ephemeral_gib must be null or between 21 and 200."
  }
}

variable "worker_cpu" {
  description = "Fargate CPU units per worker task."
  type        = number
  default     = 512
}

variable "worker_memory" {
  description = "Fargate memory (MiB) per worker task. Result pages up to the row ceiling are held in memory while a query runs."
  type        = number
  default     = 1024
}

variable "worker_ephemeral_gib" {
  description = "Fargate ephemeral storage (GiB, 21 to 200) per worker task. SQLite databases are copied from S3 under WORK_DIR before they are queried. Null: the Fargate default of 20 GiB."
  type        = number
  default     = 30
  validation {
    condition     = var.worker_ephemeral_gib == null ? true : (var.worker_ephemeral_gib >= 21 && var.worker_ephemeral_gib <= 200)
    error_message = "worker_ephemeral_gib must be null or between 21 and 200."
  }
}

variable "worker_count" {
  description = "Question worker task count. Several are safe (questions are claimed with FOR UPDATE SKIP LOCKED and leased); not autoscaled, raise it or WORKER_CONCURRENCY when the queue backs up."
  type        = number
  default     = 1
  validation {
    condition     = var.worker_count >= 1
    error_message = "worker_count must be at least 1."
  }
}

variable "scheduler_cpu" {
  description = "Fargate CPU units for the scheduler (always exactly one task)."
  type        = number
  default     = 256
}

variable "scheduler_memory" {
  description = "Fargate memory (MiB) for the scheduler."
  type        = number
  default     = 512
}

variable "scheduler_ephemeral_gib" {
  description = "Fargate ephemeral storage (GiB, 21 to 200) for the scheduler, which copies SQLite databases under WORK_DIR to refresh their schemas. Null: the Fargate default of 20 GiB."
  type        = number
  default     = null
  validation {
    condition     = var.scheduler_ephemeral_gib == null ? true : (var.scheduler_ephemeral_gib >= 21 && var.scheduler_ephemeral_gib <= 200)
    error_message = "scheduler_ephemeral_gib must be null or between 21 and 200."
  }
}

variable "web_cpu" {
  description = "Fargate CPU units per web task."
  type        = number
  default     = 512
}

variable "web_memory" {
  description = "Fargate memory (MiB) per web task."
  type        = number
  default     = 1024
}

variable "web_min_count" {
  description = "Minimum (and initial) web task count."
  type        = number
  default     = 1
}

variable "web_max_count" {
  description = "Maximum web task count under autoscaling."
  type        = number
  default     = 3
}

variable "cpu_target_percent" {
  description = "Average CPU the autoscaler aims for (api and web)."
  type        = number
  default     = 60
}

variable "idle_timeout" {
  description = "Load balancer idle timeout in seconds. Asking a question waits up to 60 seconds for its answer; this also bounds how long a stalled SQLite upload is kept."
  type        = number
  default     = 120
}

variable "deletion_protection" {
  description = "Block accidental deletion of the load balancer."
  type        = bool
  default     = true
}

variable "access_logs_bucket" {
  description = "Existing bucket for load balancer access logs (needs the ELB log-delivery bucket policy). Null disables."
  type        = string
  default     = null
}

variable "metrics_allowed_cidrs" {
  description = "Source CIDRs allowed to read /metrics through the load balancer. Empty: /metrics answers 404 at the edge."
  type        = list(string)
  default     = []
}

variable "enable_waf" {
  description = "Attach a WAF web ACL (managed rule sets plus a per-IP flood guard) to the load balancer."
  type        = bool
  default     = true
}

variable "waf_rate_limit_per_5min" {
  description = "Requests per source IP per 5 minutes before WAF blocks. Keep it high: SDK backends often sit behind one NAT address."
  type        = number
  default     = 20000
}

variable "waf_log_retention_days" {
  description = "WAF log retention."
  type        = number
  default     = 30
}

variable "source_cidrs" {
  description = "Networks of the databases people connect, which the api (connection tests, schema discovery), the worker (queries) and the scheduler (schema refresh) may reach on source_ports. Default: anywhere. Restrict it to your database networks wherever you can."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "source_ports" {
  description = "Ports of the databases people connect (PostgreSQL 5432 and MySQL 3306 by default). HTTPS 443 is always open."
  type        = list(number)
  default     = [5432, 3306]
}

variable "ai_egress" {
  description = "Extra egress from the api and worker tasks for a self-hosted model provider not on HTTPS 443, as { cidr, port } pairs (for example Ollama or vLLM inside the VPC). Empty: HTTPS only."
  type = list(object({
    cidr = string
    port = number
  }))
  default = []
}

# A boolean, not a null check on the policy: the policy is unknown until apply, and count
# must be decidable at plan time.
variable "send_mail" {
  description = "Attach mail_policy_json to the api task role (project notice mail through SES). The worker and scheduler send no mail."
  type        = bool
  default     = false
}

variable "mail_policy_json" {
  description = "IAM policy for sending notice mail (email module send_policy_json), with send_mail."
  type        = string
  default     = null
}
