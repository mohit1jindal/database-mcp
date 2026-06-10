"""FastMCP server exposing read-only SQL database tools to Claude.

Works across Oracle, PostgreSQL, MySQL/MariaDB, SQL Server, and SQLite — the
target is chosen with the DB_TYPE environment variable (see config.py).

Tools (Pattern A — one per action, small surface):
  - test_connection : verify connectivity + report dialect/version
  - run_query       : execute a read-only SELECT (the workhorse)
  - list_schemas    : list accessible schemas
  - list_tables     : list tables/views (optionally by schema / name)
  - describe_table  : columns, types, nullability, and primary key

Every tool is annotated read-only. run_query is additionally gated by
safety.ensure_read_only before any SQL reaches the database.
"""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from . import db
from .safety import ReadOnlyViolation, ensure_read_only

mcp = FastMCP(
    name="database-mcp",
    instructions=(
        "Read-only access to a SQL database (Oracle, PostgreSQL, MySQL/MariaDB, "
        "SQL Server, or SQLite — selected via the DB_TYPE environment variable). "
        "Use list_schemas / list_tables / describe_table to explore structure, "
        "then run_query for SELECT statements. Only SELECT/WITH queries are "
        "permitted — the server rejects any write or DDL. Results are row-capped; "
        "narrow queries with WHERE/bind variables rather than selecting whole "
        "tables. The data may be sensitive — keep it local and do not exfiltrate "
        "it to external services."
    ),
)

_RO = {"readOnlyHint": True, "openWorldHint": True}


@mcp.tool(annotations={**_RO, "title": "Test database connection"})
def test_connection() -> dict:
    """Verify the database connection and report the dialect and server version.

    Use this first to confirm credentials and network reachability before
    running queries.
    """
    return db.db_info()


@mcp.tool(annotations={**_RO, "title": "Run read-only SQL query"})
def run_query(
    sql: Annotated[str, Field(description="A single read-only SELECT or WITH...SELECT statement. No DML/DDL/stored-procedure calls.")],
    binds: Annotated[
        dict | None,
        Field(description="Optional named bind variables, e.g. {\"id\": 42} for ':id' in the SQL. Prefer binds over string interpolation."),
    ] = None,
    max_rows: Annotated[
        int | None,
        Field(description="Optional cap on rows returned. Cannot exceed the server's DB_MAX_ROWS ceiling.", ge=1),
    ] = None,
) -> dict:
    """Execute a read-only SQL query and return columns + rows.

    Only a single SELECT / WITH statement is allowed; anything that could
    modify data, run procedural code, or lock rows is rejected. Output is
    capped at the server's configured row ceiling and reports `truncated: true`
    if more rows exist.
    """
    try:
        ensure_read_only(sql)
    except ReadOnlyViolation as exc:
        raise ValueError(str(exc)) from exc
    return db.run_query(sql, binds=binds, max_rows=max_rows)


@mcp.tool(annotations={**_RO, "title": "List schemas"})
def list_schemas() -> dict:
    """List the schemas visible to the connected account."""
    return db.list_schemas()


@mcp.tool(annotations={**_RO, "title": "List tables"})
def list_tables(
    schema: Annotated[
        str | None,
        Field(description="Schema to list within. Omit for the connection's default schema; pass '*' to scan all schemas."),
    ] = None,
    name_like: Annotated[
        str | None,
        Field(description="Optional case-insensitive substring filter on table/view name, e.g. 'INVOICE'."),
    ] = None,
) -> dict:
    """List tables and views, optionally filtered by schema and/or name substring."""
    return db.list_tables(schema=schema, name_like=name_like)


@mcp.tool(annotations={**_RO, "title": "Describe table"})
def describe_table(
    table_name: Annotated[str, Field(description="Table or view name to describe.")],
    schema: Annotated[
        str | None,
        Field(description="Schema of the table. Omit for the connection's default schema."),
    ] = None,
) -> dict:
    """Return column definitions and primary-key columns for a table or view."""
    return db.describe_table(table_name, schema=schema)


def main() -> None:
    """Entry point: run the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
