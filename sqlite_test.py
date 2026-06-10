"""Live end-to-end test against a real SQLite database (no external server).

Proves the generic SQLAlchemy path works and exercises the v0.3 additions:
enriched describe_table (FKs/indexes), get_table_sample, EXPLAIN support, the
validator false-positive fix (a 'comment' column), and clean error handling.
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
from database_mcp.db import QueryError  # noqa: E402
from database_mcp.safety import ensure_read_only, ReadOnlyViolation  # noqa: E402

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


# --- Seed the database directly (test setup, not via the read-only server) ---
seed = create_engine(f"sqlite:///{_db_path}")
with seed.begin() as conn:
    conn.execute(text(
        "CREATE TABLE customers ("
        "id INTEGER PRIMARY KEY, name TEXT NOT NULL, comment TEXT, total REAL)"
    ))
    conn.execute(text(
        "CREATE TABLE orders ("
        "id INTEGER PRIMARY KEY, customer_id INTEGER, amount REAL, "
        "FOREIGN KEY (customer_id) REFERENCES customers(id))"
    ))
    conn.execute(text("CREATE INDEX ix_orders_customer ON orders(customer_id)"))
    conn.execute(text("INSERT INTO customers (id, name, comment, total) VALUES "
                      "(1,'Acme','vip',1284.5),(2,'Globex',NULL,982.0)"))
    conn.execute(text("INSERT INTO orders (id, customer_id, amount) VALUES "
                      "(10,1,500.0),(11,1,784.5),(12,2,982.0)"))

# --- 1. connectivity ---
info = db.db_info()
check(info.get("connected") and info.get("dialect") == "sqlite", f"db_info: {info}")

# --- 2. list_tables reports tables with a type ---
tables = db.list_tables()
tnames = {t["name"] for t in tables["tables"]}
check({"customers", "orders"} <= tnames, f"list_tables missing tables: {tables}")

# --- 3. describe_table: columns, PK, FK, index ---
desc = db.describe_table("orders")
check(desc["primary_key"] == ["id"], f"orders PK: {desc['primary_key']}")
check(len(desc["foreign_keys"]) == 1
      and desc["foreign_keys"][0]["references"]["table"] == "customers",
      f"orders FK: {desc['foreign_keys']}")
check(any(ix["columns"] == ["customer_id"] for ix in desc["indexes"]),
      f"orders indexes: {desc['indexes']}")

# --- 4. The 'comment' column must be queryable (validator false-positive fix) ---
try:
    ensure_read_only("SELECT comment FROM customers")
except ReadOnlyViolation as e:
    failures.append(f"validator wrongly blocked 'comment' column: {e}")
res = db.run_query("SELECT name, comment FROM customers ORDER BY id")
check(res["rows"][0]["comment"] == "vip", f"comment query: {res}")

# --- 5. bind variables ---
res2 = db.run_query("SELECT name FROM customers WHERE id = :id", binds={"id": 2})
check(res2["rows"][0]["name"] == "Globex", f"bind query: {res2}")

# --- 6. get_table_sample ---
sample = db.get_table_sample("orders", limit=2)
check(sample["row_count"] == 2 and "amount" in sample["columns"], f"sample: {sample}")

# --- 7. EXPLAIN is allowed by the validator ---
try:
    ensure_read_only("EXPLAIN SELECT * FROM orders")
except ReadOnlyViolation as e:
    failures.append(f"validator wrongly blocked EXPLAIN: {e}")

# --- 8. writes / write-hiding constructs are still blocked ---
for bad in [
    "DELETE FROM customers",
    "SELECT * INTO backup FROM customers",
    "WITH t AS (DELETE FROM orders RETURNING id) SELECT * FROM t",
    "SELECT 1; DROP TABLE customers",
]:
    try:
        ensure_read_only(bad)
        failures.append(f"validator FAILED to block: {bad!r}")
    except ReadOnlyViolation:
        pass

# --- 9. clean error on a bad query (no raw stack trace) ---
try:
    db.run_query("SELECT * FROM no_such_table")
    failures.append("expected QueryError for missing table")
except QueryError as e:
    check("no_such_table" in str(e).lower() or "no such table" in str(e).lower(),
          f"error message not useful: {e}")

if failures:
    print("SQLITE TEST FAILED:")
    for f in failures:
        print("  -", f)
    raise SystemExit(1)

print("SQLITE LIVE TEST PASSED (v0.3 features)")
print(f"  dialect={info['dialect']} version={info['server_version']}")
print(f"  tables={sorted(tnames)}")
print(f"  orders FK -> {desc['foreign_keys'][0]['references']['table']}, indexes={[i['name'] for i in desc['indexes']]}")
print(f"  'comment' column query OK; sample rows={sample['row_count']}; EXPLAIN allowed; writes blocked; errors clean")
