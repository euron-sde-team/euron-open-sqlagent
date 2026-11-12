# Text to SQL

How a question becomes a query: the schema block, the prompt, follow-ups, the answer
format, and the deterministic mock provider.

## The schema block

`schema/prompt.py` renders the discovered tables as plain text, one table per block:

```
Tables:
- public.orders (table, ~6000 rows)
    id integer PK
    customer_id integer -> public.customers.id
    status varchar(20) values: delivered, shipped, cancelled, returned, processing
    order_date date
    total_amount numeric(12, 2)
```

When the whole schema fits under `PROMPT_SCHEMA_CHARS` it is shown whole. Otherwise tables
are ranked by how strongly the question (and the last two turns) points at them, by table
name first and then column names and sample values, and added with the tables they
reference until the budget is spent. `values:` appears only on connections with sample
values on.

## The prompt

`sql/prompt.py` builds the messages. The system message starts with `TASK: generate`, the
dialect, today's date, a description of the database if the connection has one, the rules
(one read-only SELECT, only the listed tables, answer with one JSON object), and the schema
block. Then come up to `HISTORY_TURNS` prior answered turns of the conversation, each as
the user's question and an assistant message holding the SQL and a short summary (the
explanation, the row count, the columns and the first rows). Then the new question.

The model answers `{"sql": "...", "explanation": "..."}` or `{"sql": null, ...}` when the
schema cannot answer it. `parse_answer` also accepts the object inside a Markdown fence, a
bare `sql` fence, or plain SQL, because real models drift.

## Follow-ups

Because prior turns travel with their SQL and a result summary, "and last year?" is
answered by changing the time range of the previous query, and "break it down by channel"
by adding a grouping to it, without the person repeating anything.

## Explaining a query

`TASK: explain` carries one query in a fence and asks for two to five plain sentences.
Independently of the model, `sql/describe.py` reads the syntax tree and returns the facts
(tables, joins, filters, grouping, aggregates, ordering, limit, whether it is read-only and
why not). Nothing is executed.

## The mock provider

`providers/mock/planner.py` is a deterministic planner used by the `mock` provider kind,
by the `mockai` service (which speaks the OpenAI, Anthropic, Gemini and Ollama wire
formats) and so by every test and the demo. It parses the schema block back out of the
prompt and maps a question to SQL with fixed rules: counts, sums, averages, minimums and
maximums; grouping by a column, a related table (along foreign keys) or a time grain;
calendar filters (`in 2025`, `last year`, `this month`, `last 30 days`); filters on sampled
values; top and bottom N; listings; and follow-ups that change only what they name. It
writes dialect-specific date functions for PostgreSQL, MySQL and SQLite. A question it
cannot map gets an honest "I could not match this question". Asked to delete or drop
something, it writes the destructive statement, exactly so the guard can be seen refusing
it. It is a fixture with good manners, not a language model.
