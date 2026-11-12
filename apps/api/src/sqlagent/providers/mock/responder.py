"""How the deterministic mock answers a SQLAgent prompt, in any wire format.

The prompt (``chat/prompt.py``) names its task on the first line of the system message
(``TASK: generate`` or ``TASK: explain``) and carries the schema block and the dialect.
The mock reads those back, plans the SQL (``planner.py``) or describes the query
(``sql/describe.py``) and answers with the same JSON object a real model is asked for.
Both the in-process ``mock`` provider and the ``mockai`` service use this function, so
they always agree.
"""

from __future__ import annotations

import datetime as dt
import json
import re

from sqlagent.providers.mock.planner import plan
from sqlagent.schema.prompt import parse_block
from sqlagent.sql.describe import describe

_DIALECT = re.compile(r"^Dialect: (postgresql|mysql|sqlite)$", re.MULTILINE)
_TODAY = re.compile(r"^Today: (\d{4}-\d{2}-\d{2})$", re.MULTILINE)
_SQL_BLOCK = re.compile(r"```sql\n(.*?)\n```", re.DOTALL)


def respond(system: str, turns: list[tuple[str, str]]) -> str:
    """The answer to a prompt: ``system`` text and ``(role, content)`` turns."""
    dialect = m[1] if (m := _DIALECT.search(system)) else "postgresql"
    today = dt.date.fromisoformat(m[1]) if (m := _TODAY.search(system)) else None
    users = [content for role, content in turns if role == "user"]
    if system.startswith("TASK: explain"):
        text = users[-1] if users else ""
        sql = m[1] if (m := _SQL_BLOCK.search(text)) else text
        return json.dumps({"explanation": describe(sql, dialect)})
    if not system.startswith("TASK: generate"):
        return json.dumps({"answer": "This mock only answers SQLAgent prompts."})
    tables = parse_block(system)
    questions = [_question(u) for u in users]
    result = plan(tables, questions, dialect, today)
    if result.sql is None:
        return json.dumps({"sql": None, "explanation": result.note})
    return json.dumps({"sql": result.sql, "explanation": describe(result.sql, dialect)})


def _question(text: str) -> str:
    """The question inside a user turn (the engine wraps it in a line of context)."""
    for line in text.splitlines():
        if line.startswith("Question: "):
            return line[len("Question: ") :]
    return text
