from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import Field

from sqlagent.charts.suggest import ChartSuggestion, ColumnIn, suggest
from sqlagent.core.schemas import ApiModel
from sqlagent.projects.access import Viewer

router = APIRouter(prefix="/api/v1/projects/{project_id}/charts", tags=["charts"])


class SuggestRequest(ApiModel):
    columns: list[ColumnIn] = Field(max_length=200)
    rows: list[list[Any]] = Field(max_length=5000)


class SuggestOut(ApiModel):
    chart: ChartSuggestion | None


@router.post(
    "/suggest",
    response_model=SuggestOut,
    summary="Which chart (bar, line, pie) fits a result's shape, if any",
)
async def suggest_chart(body: SuggestRequest, _: Viewer) -> SuggestOut:
    return SuggestOut(chart=suggest(body.columns, body.rows))
