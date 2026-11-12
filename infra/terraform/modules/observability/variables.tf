variable "name_prefix" {
  description = "Prefix for every resource name."
  type        = string
}

variable "log_retention_days" {
  description = "CloudWatch log retention for the app log groups."
  type        = number
  default     = 30
}

variable "logs_kms_key_arn" {
  description = "CMK for the log groups (its key policy must allow CloudWatch Logs, as the kms module's does). Null uses CloudWatch's default encryption."
  type        = string
  default     = null
}

variable "alarm_email" {
  description = "Address subscribed to alarm notifications (confirm the e-mail AWS sends). Null: subscribe something else to the topic."
  type        = string
  default     = null
}

variable "alb_arn_suffix" {
  description = "Load balancer ARN suffix."
  type        = string
}

variable "ecs_cluster_name" {
  description = "ECS cluster name."
  type        = string
}

variable "lb_services" {
  description = "Load-balanced services (service module `services`): { api = { service_name, target_group_arn_suffix }, web = { ... } }. Must contain api."
  type = map(object({
    service_name            = string
    target_group_arn_suffix = string
  }))
  validation {
    condition     = contains(keys(var.lb_services), "api")
    error_message = "lb_services must contain api."
  }
}

variable "ecs_services" {
  description = "Every ECS service to watch for CPU and memory (service module `service_names`): { api = \"api\", worker = \"worker\", scheduler = \"scheduler\", web = \"web\" }."
  type        = map(string)
}

variable "db_instance_identifier" {
  description = "RDS instance identifier."
  type        = string
}

variable "db_max_connections" {
  description = "Connection ceiling the alarm measures against."
  type        = number
  default     = 200
}

variable "cache_replication_group_id" {
  description = "ElastiCache replication group id; nodes are <id>-001, <id>-002, ..."
  type        = string
}

variable "cache_node_count" {
  description = "Nodes in the replication group (cache module num_cache_clusters)."
  type        = number
  default     = 1
}

variable "target_5xx_threshold" {
  description = "5xx responses per 5 minutes (per app, and at the load balancer) that raise an alarm."
  type        = number
  default     = 25
}

variable "api_p95_latency_seconds" {
  description = "api p95 time to first byte that raises an alarm. Asking a question waits up to 60 seconds for its answer, and generate, explain and execute call the model or the database directly, so keep it generous."
  type        = number
  default     = 30
}

variable "question_finished_log_pattern" {
  description = "CloudWatch Logs JSON filter matching the worker's `question finished` line (one per question, any status)."
  type        = string
  default     = "{ $.msg = \"question finished\" }"
}

variable "question_failed_log_pattern" {
  description = "CloudWatch Logs JSON filter matching a question that finished with status failed."
  type        = string
  default     = "{ ($.msg = \"question finished\") && ($.status = \"failed\") }"
}

variable "query_refused_log_pattern" {
  description = "CloudWatch Logs JSON filter matching the `query refused` line the api and the worker log when the SQL guard refuses a query."
  type        = string
  default     = "{ $.msg = \"query refused\" }"
}

variable "question_queue_log_pattern" {
  description = "CloudWatch Logs JSON filter matching the scheduler's `question queue` line (its `queued` field becomes the metric)."
  type        = string
  default     = "{ $.msg = \"question queue\" }"
}

variable "error_log_pattern" {
  description = "CloudWatch Logs JSON filter matching an error line, applied to the worker and the scheduler log groups."
  type        = string
  default     = "{ $.level = \"error\" }"
}

variable "question_failure_threshold" {
  description = "Failed questions per 5 minutes that raise an alarm. Some failures are outside the deployment (a connected database down, an expired provider key), so this is a rate, not zero."
  type        = number
  default     = 10
}

variable "query_refusal_threshold" {
  description = "SQL guard refusals per 15 minutes (api and worker together) that raise an alarm. Models occasionally write a refused query; a spike can mean someone probing the guard."
  type        = number
  default     = 20
}

variable "queue_backlog_threshold" {
  description = "Questions waiting for a worker, sustained for 15 minutes, that raise an alarm (workers down or saturated)."
  type        = number
  default     = 50
}

variable "error_threshold" {
  description = "Error lines per 5 minutes from the worker, or from the scheduler, that raise an alarm."
  type        = number
  default     = 5
}
