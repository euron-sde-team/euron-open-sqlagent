# Walkthrough of the demo

`make demo` builds three databases and a working SQLAgent around them. This tour follows
what each screen shows and why.

## The data

| Database | Engine | Tables |
| --- | --- | --- |
| `shop` | PostgreSQL | customers (400), products (33), orders (6,000 over three years), order items, a monthly revenue view |
| `people` | MySQL | departments (7), employees (320), leave requests |
| `subscriptions` | SQLite file | plans, accounts (240), invoices |

Each has a read-only login, `sqlagent_reader`, which is what the demo connections use.
Dates run up to today, so "this year" and "last year" always have data.

## Overview

The project's last 14 days: questions per day (answered and refused), the share answered,
how many the guard refused (they never reached a database), the median query time, the
databases with their table counts, recent conversations and templates you can run.

## Ask

A conversation is a thread of questions on one database. Each answer shows its status,
the guard's badge, the model that wrote it and how long the whole answer took, then the SQL,
an explanation, and the result. When the result has one category and one or more numbers,
a chart is shown (a line over time, a pie for a few parts, bars otherwise) and you can
switch to another type that fits or back to the table. Pages are read from the stored
snapshot, and **CSV** downloads it.

Follow-ups see the conversation: "How many orders were placed this year?", then "and last
year?" changes only the date range, and "break it down by channel" adds a grouping.

The conversation "Delete all cancelled orders" shows a refusal: the model wrote a
`DELETE`, the guard refused it (`only SELECT queries run`), and the audit log has a
`query.refused` entry.

## Connections and the schema explorer

Each connection shows its kind, where it points, its limits (row limit, timeout), whether
its last test passed and the server version. **Schema** lists every table and view the
login can read with columns, types, keys, foreign keys, indexes, approximate row counts and
(where sampling is on) the example values the model sees.

## History and templates

**History** lists conversations (searchable) and every query run or refused with its
status, rows and duration. **Templates** are saved questions; the demo's templates have
already been run twice each.

## Audit log and settings

Project admins see the append-only audit log, filtered by database or person. **Settings**
has members and their roles, model providers (the built-in mock is the default; a
"gateway" provider points at the mock service through the OpenAI-compatible adapter), API
keys and the organization. Instance admins also see users, system status and instance
settings.

Sign in as the viewer to see the same screens without any control that asks, runs or
changes anything.
