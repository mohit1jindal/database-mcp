"""Live end-to-end test against a real SQLite database (no external server).

Proves the generic SQLAlchemy path works: build a DB from env config, create a
table + rows directly, then exercise the read-only tools (run_query,
list_tables, describe_table) and confirm the safety layer blocks a write.
"""

import os
import tempfile

# Configure the server for SQLite BEFORE importing the package (config reads env).
_tmp = tempfile.mkdtemp()
_db_path = os.path.join(_tmp, "demo.db")
os.environ["DB_TYPE"] = "sqlite"
os.environ["DB_NAME"] = _db_path

from sqlalchemy import create_engine, text  # noqa: E402

from database_mcp import db  # noqa: E402
from database_mcp.safety import ensure_read_only, ReadOnlyViolation  # noqa: E402

failures = []

# Seed the database directly (this is test setup, not via the read-only server).
seed = create_engine(f"sqlite:///{_db_path}")
with seed.begin() as conn:
    conn.execute(text(
        "CREATE TABLE customers ("
        "id INTEGER PRIMARY KEY, name TEXT NOT NULL, total REAL, created TIMESTAMP)"
    ))
    conn.execute(
        text("INSERT INTO customers (id, name, total, created) VALUES (:id, :name, :total, :created)"),
        [
            {"id": 1, "name": "Acme", "total": 1284.50, "created": "2024-01-02 10:00:00"},
            {"id": 2, "name": "Globex", "total": 982.00, "created": "2024-03-15 12:30:00"},
        ],
    )

# 1. test_connection / db_info
info = db.db_info()
if info.get("dialect") != "sqlite" or not info.get("connected"):
    failures.append(f"db_info unexpected: {info}")

# 2. list_tables finds our table
tables = db.list_tables()
names = {t["name"] for t in tables["tables"]}
if "customers" not in names:
    failures.append(f"list_tables missing 'customers': {tables}")

# 3. describe_table returns columns + PK
desc = db.describe_table("customers")
colnames = [c["name"] for c in desc["columns"]]
if "name" not in colnames or desc["primary_key"] != ["id"]:
    failures.append(f"describe_table unexpected: {desc}")

# 4. run_query returns rows with converted types
res = db.run_query("SELECT id, name, total FROM customers ORDER BY total DESC")
if res["row_count"] != 2 or res["rows"][0]["name"] != "Acme":
    failures.append(f"run_query unexpected: {res}")

# 5. bind variables work
res2 = db.run_query("SELECT name FROM customers WHERE id = :id", binds={"id": 2})
if res2["rows"][0]["name"] != "Globex":
    failures.append(f"bind query unexpected: {res2}")

# 6. safety layer blocks a write before it reaches the DB
try:
    ensure_read_only("DELETE FROM customers")
    failures.append("safety layer FAILED to block DELETE")
except ReadOnlyViolation:
    pass

if failures:
    print("SQLITE TEST FAILED:")
    for f in failures:
        print("  -", f)
    raise SystemExit(1)

print("SQLITE LIVE TEST PASSED")
print(f"  dialect={info['dialect']} version={info['server_version']}")
print(f"  list_tables found: {sorted(names)}")
print(f"  describe_table PK: {desc['primary_key']}, cols: {colnames}")
print(f"  run_query top row: {res['rows'][0]}")
