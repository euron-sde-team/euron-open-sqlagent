from __future__ import annotations

import uuid
from datetime import date

from sqlagent.core.schemas import ApiModel


class UsageCounts(ApiModel):
    questions: int = 0
    answered: int = 0
    refused: int = 0
    failed: int = 0
    executions: int = 0
    rows_returned: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class UsageByDay(UsageCounts):
    day: date


class UsageByConnection(UsageCounts):
    connection_id: uuid.UUID
    connection: str


class UsageByModel(UsageCounts):
    model: str


class UsageReport(ApiModel):
    days: int
    since: date
    by_day: list[UsageByDay]
    by_connection: list[UsageByConnection]
    by_model: list[UsageByModel]
