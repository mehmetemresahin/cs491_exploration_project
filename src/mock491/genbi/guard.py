"""Check generated SQL before it runs: one read-only SELECT over the catalog tables only.

The sandbox already makes anything else impossible (catalog.py); this check turns a bad query
into a clear message instead of an engine error, and is a second line of defence.
"""

import json
import threading

import duckdb
import pandas as pd

MAX_ROWS = 500
TIMEOUT_SECONDS = 5.0


class UnsafeQuery(ValueError):
    """The SQL is not a single SELECT over the allowed tables."""


def _walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def check(sql: str, allowed: frozenset[str]) -> str:
    """Return the statement (trailing semicolon removed) or raise UnsafeQuery."""
    parser = duckdb.connect(":memory:")
    try:
        statements = parser.extract_statements(sql)
    except duckdb.Error as e:
        raise UnsafeQuery(f"Not valid SQL: {e}") from e
    if len(statements) != 1:
        raise UnsafeQuery("Exactly one statement is allowed.")
    if statements[0].type != duckdb.StatementType.SELECT:
        raise UnsafeQuery("Only SELECT queries are allowed.")

    (raw,) = parser.execute("SELECT json_serialize_sql($sql)", {"sql": sql}).fetchone()
    tree = json.loads(raw)
    if tree.get("error"):
        raise UnsafeQuery(f"Not valid SQL: {tree.get('error_message', 'parse error')}")
    ctes = {
        entry["key"] for node in _walk(tree) for entry in node.get("cte_map", {}).get("map", [])
    }
    for node in _walk(tree):
        kind = node.get("type")
        if kind == "TABLE_FUNCTION":
            raise UnsafeQuery("Table functions (reading files or other sources) are not allowed.")
        if kind == "BASE_TABLE":
            name = node["table_name"].lower()
            if node.get("catalog_name") or node.get("schema_name"):
                raise UnsafeQuery(f"Use plain table names, not '{node['schema_name']}.{name}'.")
            if name not in allowed and name not in ctes:
                raise UnsafeQuery(f"Unknown table '{name}'. Allowed: {', '.join(sorted(allowed))}.")
    return statements[0].query.strip().rstrip(";")


def run(box: duckdb.DuckDBPyConnection, sql: str) -> tuple[pd.DataFrame, bool]:
    """Run on the sandbox with a time limit; returns (rows, truncated)."""
    timer = threading.Timer(TIMEOUT_SECONDS, box.interrupt)
    timer.start()
    try:
        cur = box.execute(sql)
        columns = [d[0] for d in cur.description]
        rows = cur.fetchmany(MAX_ROWS + 1)
    except duckdb.InterruptException as e:
        raise UnsafeQuery(f"The query took longer than {TIMEOUT_SECONDS:.0f}s.") from e
    finally:
        timer.cancel()
    return pd.DataFrame(rows[:MAX_ROWS], columns=columns), len(rows) > MAX_ROWS
