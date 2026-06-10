"""Offline smoke test — no database required.

Verifies imports, that the read-only validator accepts safe queries and
rejects unsafe ones, and that the FastMCP tools are registered.
"""

import sqlalchemy  # noqa: F401
import fastmcp  # noqa: F401

from database_mcp.safety import ensure_read_only, ReadOnlyViolation
from database_mcp import server

ALLOWED = [
    "SELECT 1 FROM dual",
    "select * from invoices where id = :id",
    "WITH t AS (SELECT 1 x FROM dual) SELECT x FROM t",
    "SELECT name FROM users -- a comment\n WHERE name = 'bob; drop'",
    "SELECT 1 FROM dual;",
    # Common column names / functions that must NOT trip the validator:
    "SELECT comment FROM tickets",
    "SELECT REPLACE(name, 'a', 'b') AS n FROM users",
    "SELECT lock_id, set_count FROM jobs",
    # EXPLAIN is permitted (read-only plan inspection):
    "EXPLAIN SELECT * FROM orders",
]

BLOCKED = [
    "UPDATE invoices SET total = 0",
    "DELETE FROM users",
    "INSERT INTO t VALUES (1)",
    "DROP TABLE t",
    "SELECT 1 FROM dual; DELETE FROM t",
    "BEGIN DBMS_OUTPUT.PUT_LINE('x'); END;",
    "SELECT * FROM t FOR UPDATE",
    "MERGE INTO t USING s ON (t.id=s.id) WHEN MATCHED THEN UPDATE SET t.v=s.v",
    "SELECT * FROM t INTO v_x",
    "",
]

failures = []

for sql in ALLOWED:
    try:
        ensure_read_only(sql)
    except ReadOnlyViolation as e:
        failures.append(f"FALSE POSITIVE (should allow): {sql!r} -> {e}")

for sql in BLOCKED:
    try:
        ensure_read_only(sql)
        failures.append(f"FALSE NEGATIVE (should block): {sql!r}")
    except ReadOnlyViolation:
        pass

tool_names = set()
try:
    import asyncio
    tools = asyncio.run(server.mcp.list_tools())
    tool_names = {t.name for t in tools}
except Exception as e:  # pragma: no cover
    failures.append(f"could not enumerate tools: {e}")

expected = {"test_connection", "run_query", "list_schemas", "list_tables", "describe_table", "get_table_sample"}
missing = expected - tool_names
if missing:
    failures.append(f"missing tools: {missing}")

if failures:
    print("SMOKE TEST FAILED:")
    for f in failures:
        print("  -", f)
    raise SystemExit(1)

print("SMOKE TEST PASSED")
print("  read-only validator: %d allowed, %d blocked — all correct" % (len(ALLOWED), len(BLOCKED)))
print("  registered tools:", sorted(tool_names))
