# euron-sqlagent (Python SDK and CLI)

The Python client for [Euron Open SQLAgent](../../README.md): ask a connected database a
question in plain English, get one validated read-only SQL query and its result; generate,
validate, explain and run SQL; read conversations and templates. Python 3.10+, one
dependency (`httpx`). A sync client (`SQLAgent`) and an async one (`AsyncSQLAgent`) with the
same methods.

```python
from euron_sqlagent import SQLAgent

client = SQLAgent(base_url="http://localhost:5430", api_key="sqa_...")

answer = client.ask("How many orders per status?", connection="Shop (PostgreSQL)")
print(answer.sql)          # the generated query, accepted by the SQL guard
print(answer.records())    # [{"status": "delivered", "order_count": 4211}, ...]
print(answer.chart)        # Chart(type="pie", x="status", y=["order_count"], ...)

follow_up = client.ask("and last year?", conversation=answer.conversation_id)

client.explain("SELECT ... FROM orders ...", connection="Shop (PostgreSQL)")   # never runs it
client.validate("DELETE FROM orders", dialect="postgresql")                  # {"valid": False, ...}
result = client.execute("SELECT name FROM products", connection="Shop (PostgreSQL)")
csv_text = client.csv(result.id)
```

The API key (Settings, API keys in the dashboard) selects the project. It needs the `read`
scope to read and `query` to ask questions and run SQL.

## Command line

```bash
pip install ./sdk/python
export SQLAGENT_URL=http://localhost:5430 SQLAGENT_API_KEY=sqa_...

sqlagent-cli connections
sqlagent-cli ask "Shop (PostgreSQL)" "Monthly revenue this year"
sqlagent-cli ask --conversation <id> "and last year?"
sqlagent-cli explain "SELECT status, count(*) FROM orders GROUP BY status" --dialect postgresql
sqlagent-cli validate "DROP TABLE orders" --dialect postgresql      # exits 1: refused
sqlagent-cli run "Shop (PostgreSQL)" "SELECT count(*) FROM orders" --csv
```

`ask`, `run` and `template` exit 0 when the query ran and 1 otherwise, so a scheduled CI job
can fail when a report stops working.

MIT licensed, part of Euron Open SQLAgent.
