"""Prometheus metrics. The API and the worker each expose their own registry."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

QUESTIONS = Counter("sqlagent_questions_total", "Questions that reached a final state", ["status"])
QUESTION_SECONDS = Histogram(
    "sqlagent_question_seconds",
    "Question duration from claim to final state (model, guard, execution)",
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)
GUARD_REFUSALS = Counter(
    "sqlagent_guard_refusals_total", "Queries the SQL guard refused, by rule", ["code"]
)
GUARD_SECONDS = Histogram(
    "sqlagent_guard_seconds",
    "Time the SQL guard spends parsing and checking one query",
    buckets=(0.0001, 0.00025, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05),
)
EXECUTIONS = Counter(
    "sqlagent_executions_total", "Queries against connected databases", ["dialect", "status"]
)
MODEL_CALLS = Counter("sqlagent_model_calls_total", "Model calls", ["kind", "outcome"])
MODEL_LATENCY = Histogram(
    "sqlagent_model_latency_seconds",
    "Model call latency",
    ["kind"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 16, 32, 64, 128),
)
TOKENS = Counter("sqlagent_tokens_total", "Model tokens", ["direction"])
QUEUE_DEPTH = Gauge("sqlagent_queue_depth", "Questions by state", ["status"])
SCHEMA_REFRESHES = Counter("sqlagent_schema_refreshes_total", "Schema discoveries", ["outcome"])
DEPENDENCY_ERRORS = Counter(
    "sqlagent_dependency_errors_total",
    "Failed calls to a dependency",
    ["dependency", "operation"],
)
