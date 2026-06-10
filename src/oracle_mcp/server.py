"""FastMCP server exposing read-only Oracle tools to Claude.

Tools (Pattern A — one per action, small surface):
  - test_connection : verify connectivity + report DB version
  - run_query       : execute a read-only SELECT (the workhorse)
  - list_schemas    : list accessible schemas/owners
  - list_tables     : list tables (optionally filtered by owner / name)
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
    name="oracle-mcp",
    instructions=(
        "Read-only access to an Oracle database. Use list_schemas / "
        "list_tables / describe_table to explore structure, then run_query for "
        "SELECT statements. Only SELECT/WITH queries are permitted — the server "
        "rejects any write or DDL. Results are row-capped; narrow queries with "
        "WHERE/bind variables rather than selecting whole tables. The data may "
        "be sensitive — keep it local and do not exfiltrate it to external "
        "services."
    ),
)

_RO = {"readOnlyHint": True, "openWorldHint": True}


@mcp.tool(annotations={**_RO, "title": "Test Oracle connection"})
def test_connection() -> dict:
    """Verify the database connection and return the Oracle server version.

    Use this first to confirm credentials and network reachability before
    running queries.
    """
    return {"connected": True, "version": db.db_version()}


@mcp.tool(annotations={**_RO, "title": "Run read-only SQL query"})
def run_query(
    sql: Annotated[str, Field(description="A single read-only SELECT or WITH...SELECT statement. No DML/DDL/PLSQL.")],
    binds: Annotated[
        dict | None,
        Field(description="Optional named bind variables, e.g. {\"id\": 42} for ':id' in the SQL. Prefer binds over string interpolation."),
    ] = None,
    max_rows: Annotated[
        int | None,
        Field(description="Optional cap on rows returned. Cannot exceed the server's ORACLE_MAX_ROWS ceiling.", ge=1),
    ] = None,
) -> dict:
    """Execute a read-only SQL query and return columns + rows.

    Only a single SELECT / WITH statement is allowed; anything that could
    modify data, run PL/SQL, or lock rows is rejected. Output is capped at the
    server's configured row ceiling and reports `truncated: true` if more rows
    exist.
    """
    try:
        ensure_read_only(sql)
    except ReadOnlyViolation as exc:
        raise ValueError(str(exc)) from exc
    return db.run_query(sql, binds=binds, max_rows=max_rows)


@mcp.tool(annotations={**_RO, "title": "List schemas"})
def list_schemas() -> dict:
    """List the schemas/owners visible to the connected account."""
    return db.run_query(
        "SELECT username FROM all_users ORDER BY username",
        max_rows=10000,
    )


@mcp.tool(annotations={**_RO, "title": "List tables"})
def list_tables(
    owner: Annotated[
        str | None,
        Field(description="Schema/owner to filter by (case-insensitive). Omit to list across all accessible schemas."),
    ] = None,
    name_like: Annotated[
        str | None,
        Field(description="Optional case-insensitive substring filter on table name, e.g. 'INVOICE'."),
    ] = None,
) -> dict:
    """List tables, optionally filtered by owner and/or name substring."""
    clauses = []
    binds: dict = {}
    if owner:
        clauses.append("UPPER(owner) = UPPER(:owner)")
        binds["owner"] = owner
    if name_like:
        clauses.append("UPPER(table_name) LIKE UPPER('%' || :name_like || '%')")
        binds["name_like"] = name_like
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = (
        "SELECT owner, table_name, num_rows "
        "FROM all_tables "
        f"{where} "
        "ORDER BY owner, table_name"
    )
    return db.run_query(sql, binds=binds, max_rows=5000)


@mcp.tool(annotations={**_RO, "title": "Describe table"})
def describe_table(
    table_name: Annotated[str, Field(description="Table name to describe (case-insensitive).")],
    owner: Annotated[
        str | None,
        Field(description="Schema/owner of the table. Omit to search across accessible schemas."),
    ] = None,
) -> dict:
    """Return column definitions and primary-key columns for a table."""
    binds: dict = {"t": table_name}
    owner_clause = ""
    if owner:
        owner_clause = "AND UPPER(c.owner) = UPPER(:owner)"
        binds["owner"] = owner

    columns_sql = (
        "SELECT c.owner, c.column_name, c.data_type, c.data_length, "
        "c.data_precision, c.data_scale, c.nullable, c.column_id "
        "FROM all_tab_columns c "
        "WHERE UPPER(c.table_name) = UPPER(:t) "
        f"{owner_clause} "
        "ORDER BY c.owner, c.column_id"
    )
    columns = db.run_query(columns_sql, binds=binds, max_rows=5000)

    pk_binds: dict = {"t": table_name}
    pk_owner_clause = ""
    if owner:
        pk_owner_clause = "AND UPPER(cons.owner) = UPPER(:owner)"
        pk_binds["owner"] = owner
    pk_sql = (
        "SELECT cols.column_name, cols.position "
        "FROM all_constraints cons "
        "JOIN all_cons_columns cols "
        "  ON cons.owner = cols.owner "
        " AND cons.constraint_name = cols.constraint_name "
        "WHERE cons.constraint_type = 'P' "
        "AND UPPER(cons.table_name) = UPPER(:t) "
        f"{pk_owner_clause} "
        "ORDER BY cols.position"
    )
    pk = db.run_query(pk_sql, binds=pk_binds, max_rows=100)

    return {
        "table": table_name,
        "owner": owner,
        "columns": columns["rows"],
        "primary_key": [r["COLUMN_NAME"] for r in pk["rows"]],
    }


def main() -> None:
    """Entry point: run the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
