"""``sqlagent-cli``: ask your databases questions from a terminal or CI.

    export SQLAGENT_URL=http://localhost:5430 SQLAGENT_API_KEY=sqa_...
    sqlagent-cli connections
    sqlagent-cli schema "Shop (PostgreSQL)"
    sqlagent-cli ask "Shop (PostgreSQL)" "How many orders per status?" [--json | --csv]
    sqlagent-cli ask --conversation <id> "and last year?"
    sqlagent-cli explain "SELECT ..." [--connection NAME | --dialect postgresql]
    sqlagent-cli validate "SELECT ..." --dialect mysql
    sqlagent-cli run "Shop (PostgreSQL)" "SELECT ..." [--json | --csv]
    sqlagent-cli templates
    sqlagent-cli template <template id>

``ask``, ``run`` and ``template`` exit 0 when the query ran, 1 otherwise (refused, failed,
no answer), and ``validate`` exits 1 for a query the guard refuses, so they fit in CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from euron_sqlagent.client import SQLAgent
from euron_sqlagent.errors import SQLAgentError
from euron_sqlagent.models import Answer, Execution


def _table(columns: list[str], rows: list[list[Any]], limit: int = 50) -> str:
    cells = [[("" if v is None else str(v)) for v in r] for r in rows[:limit]]
    widths = [min(max([len(c)] + [len(r[i]) for r in cells]), 40) for i, c in enumerate(columns)]

    def line(values: list[str]) -> str:
        return "  ".join(v[:w].ljust(w) for v, w in zip(values, widths, strict=False))

    out = [line(columns), line(["-" * w for w in widths])]
    out += [line(r) for r in cells]
    if len(rows) > limit:
        out.append(f"... {len(rows) - limit} more rows")
    return "\n".join(out)


def _print_answer(a: Answer, client: SQLAgent, fmt: str) -> int:
    if fmt == "json":
        print(json.dumps(a.raw, indent=2, default=str))
    elif fmt == "csv" and a.execution_id and a.ok:
        sys.stdout.write(client.csv(a.execution_id))
    else:
        print(f"[{a.status}] {a.question}")
        if a.sql:
            badge = "validated read-only" if a.validated else "NOT validated"
            print(f"\n-- SQL ({badge})\n{a.sql}\n")
        if a.explanation:
            print(a.explanation + "\n")
        if a.ok:
            print(_table(a.columns, a.rows))
            if a.chart:
                print(f"\nchart: {a.chart.type} of {', '.join(a.chart.y)} by {a.chart.x}")
        elif a.error:
            print(f"error: {a.error}")
        print(f"\nconversation: {a.conversation_id}")
    return 0 if a.ok else 1


def _print_execution(e: Execution, client: SQLAgent, fmt: str) -> int:
    if fmt == "json":
        print(json.dumps(e.raw, indent=2, default=str))
    elif fmt == "csv" and e.ok:
        sys.stdout.write(client.csv(e.id))
    elif e.ok:
        print(_table(e.columns, e.rows))
        cut = " (cut at the connection's row limit)" if e.truncated else ""
        print(f"\n{e.row_count} rows in {e.duration_ms:.0f} ms{cut}")
    else:
        print(f"[{e.status}] {e.error}")
    return 0 if e.ok else 1


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="sqlagent-cli", description="Euron Open SQLAgent")
    parser.add_argument("--url", help="API URL (default $SQLAGENT_URL)")
    parser.add_argument("--api-key", help="project API key (default $SQLAGENT_API_KEY)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("connections", help="list the project's connections")
    p = sub.add_parser("schema", help="tables and columns of a connection")
    p.add_argument("connection")
    p.add_argument("--refresh", action="store_true")
    p = sub.add_parser("ask", help="ask a question in plain English")
    p.add_argument("connection", nargs="?", help="connection name or id (new conversations)")
    p.add_argument("question")
    p.add_argument("--conversation", help="follow up in this conversation")
    p.add_argument("--wait", type=float, default=60.0)
    p.add_argument("--json", dest="fmt", action="store_const", const="json", default="text")
    p.add_argument("--csv", dest="fmt", action="store_const", const="csv")
    p = sub.add_parser("explain", help="explain a query in plain language (never runs it)")
    p.add_argument("sql")
    p.add_argument("--connection")
    p.add_argument("--dialect", choices=["postgresql", "mysql", "sqlite"])
    p.add_argument("--no-model", action="store_true", help="explain from the syntax tree only")
    p = sub.add_parser("validate", help="is this exactly one read-only SELECT?")
    p.add_argument("sql")
    p.add_argument("--connection")
    p.add_argument("--dialect", choices=["postgresql", "mysql", "sqlite"])
    p = sub.add_parser("run", help="run a read-only query on a connection")
    p.add_argument("connection")
    p.add_argument("sql")
    p.add_argument("--json", dest="fmt", action="store_const", const="json", default="text")
    p.add_argument("--csv", dest="fmt", action="store_const", const="csv")
    sub.add_parser("templates", help="saved questions")
    p = sub.add_parser("template", help="ask a saved question again")
    p.add_argument("template_id")
    p.add_argument("--json", dest="fmt", action="store_const", const="json", default="text")
    args = parser.parse_args(argv)

    code = 0
    try:
        with SQLAgent(args.url, args.api_key) as client:
            if args.command == "connections":
                for c in client.connections():
                    where = c.get("database") or c.get("file_name") or ""
                    print(f"{c['id']}  {c['kind']:<10}  {c['name']}  ({where})")
            elif args.command == "schema":
                schema = client.schema(args.connection, refresh=args.refresh)
                for t in schema["tables"]:
                    name = f"{t['schema_name']}.{t['name']}" if t.get("schema_name") else t["name"]
                    cols = ", ".join(c["name"] for c in t["columns"])
                    print(f"{name} ({t['kind']}, {t.get('row_count') or '?'} rows): {cols}")
            elif args.command == "ask":
                if not args.connection and not args.conversation:
                    parser.error("ask needs a connection, or --conversation for a follow-up")
                answer = client.ask(
                    args.question,
                    connection=args.connection,
                    conversation=args.conversation,
                    wait=args.wait,
                )
                code = _print_answer(answer, client, args.fmt)
            elif args.command == "explain":
                out = client.explain(
                    args.sql,
                    connection=args.connection,
                    dialect=args.dialect,
                    use_model=not args.no_model,
                )
                print(out["explanation"])
                flag = "read-only" if out["analysis"]["read_only"] else "NOT read-only"
                print(f"\n({flag}; tables: {', '.join(out['analysis']['tables']) or 'none'})")
            elif args.command == "validate":
                v = client.validate(args.sql, connection=args.connection, dialect=args.dialect)
                print("valid: one read-only query" if v["valid"] else f"refused: {v['reason']}")
                code = 0 if v["valid"] else 1
            elif args.command == "run":
                code = _print_execution(
                    client.execute(args.sql, connection=args.connection), client, args.fmt
                )
            elif args.command == "templates":
                for t in client.templates():
                    print(f"{t['id']}  {t['name']}: {t['question']}  ({t['connection_name']})")
            elif args.command == "template":
                code = _print_answer(client.run_template(args.template_id), client, args.fmt)
    except SQLAgentError as exc:
        print(f"error: {exc.message} ({exc.code})", file=sys.stderr)
        code = 2
    sys.exit(code)


if __name__ == "__main__":
    main()
