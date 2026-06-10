# Use Cases & Features

`oracle-mcp` gives an AI assistant **safe, read-only, native access** to an
Oracle database. Instead of copy-pasting SQL between a database client and your
chat, the assistant explores the real schema and data itself — then helps you
understand it, write against it, and debug.

This document covers what the server can do, the tools it exposes, and the
workflows it's built for.

---

## Design philosophy

- **Read-only by design.** The server can never modify data. `SELECT` / `WITH`
  only — every write, DDL, PL/SQL block, row-lock, or multi-statement input is
  rejected before it reaches the database.
- **Local and private.** It runs on your machine over stdio. Query results stay
  in your environment.
- **No secrets in code.** All connection settings come from environment
  variables.
- **Bounded output.** Every result is row-capped so a stray `SELECT *` can't
  flood your session.

---

## Feature summary

| Capability | Detail |
|------------|--------|
| Schema discovery | List schemas, tables (filterable), and full column/PK definitions |
| Read-only querying | Parameterized `SELECT` / `WITH` with bind variables |
| Safety enforcement | Allowlist validation; comments & string literals stripped before checks |
| Bounded results | `ORACLE_MAX_ROWS` ceiling; `truncated` flag when more rows exist |
| Query timeouts | `ORACLE_QUERY_TIMEOUT` cancels long-running queries |
| Thin-mode driver | No Oracle Instant Client install required |
| TLS / wallet support | Oracle Cloud / mTLS via config dir + wallet |
| Connection pooling | Small pool, connections rolled back on release |
| Type-safe output | Dates → ISO strings, numbers preserved, LOBs/blobs summarized, long text truncated |

---

## Tool reference

### `test_connection()`
Verifies connectivity and returns the Oracle server version. Use it first to
confirm credentials and reachability.

### `run_query(sql, binds?, max_rows?)`
Runs a single read-only `SELECT` / `WITH` statement.
- `sql` — one statement; no DML/DDL/PL-SQL.
- `binds` — optional named bind variables, e.g. `{"id": 42}` for `:id`. Prefer
  binds over string interpolation.
- `max_rows` — optional cap; cannot exceed the `ORACLE_MAX_ROWS` ceiling.
- **Returns:** `{ columns, rows, row_count, truncated, limit }`.

### `list_schemas()`
Lists the schemas/owners visible to the connected account.

### `list_tables(owner?, name_like?)`
Lists tables, optionally filtered by owner and/or a case-insensitive name
substring (e.g. `name_like="INVOICE"`). Returns owner, table name, and row-count
estimate.

### `describe_table(table_name, owner?)`
Returns column definitions (name, type, length/precision/scale, nullability,
ordinal) plus the primary-key columns for a table.

---

## Use cases

### 1. Understand an unfamiliar or legacy database
Large databases accumulate hundreds of tables with cryptic names and
undocumented relationships. Instead of spelunking by hand:

> *"What tables are in the SALES schema? Describe the ones related to orders."*

The assistant uses `list_tables` + `describe_table` to map the structure and
explain it back in plain language.

### 2. Figure out where data lives (table/column mapping)
Before writing a query or a load script, you need to know which table and
column a field belongs in.

> *"Where is a customer's billing address stored, and what are the column names?"*

The assistant inspects the real schema and (with `run_query`) a few sample rows
to confirm — so your mapping is grounded in the actual data, not a guess.

### 3. Write and debug SQL faster
Because the assistant can see the true structure, it writes queries that match
your schema and catches mistakes early:

> *"Write a query for the top 10 customers by total order value in the last quarter."*

It validates column/table names against `describe_table`, runs the query
read-only, inspects the result shape, and iterates — turning a write-run-fix
loop into a conversation.

### 4. Move data between systems (source → target migration)
Connect a **source** and a **target** database (see the configuration guide for
two-instance setup). Then:

> *"Here's my field mapping from SOURCE.CUSTOMERS to TARGET.CLIENT. Generate the
> migration script."*

The assistant reads both schemas, applies your transformation logic, and
**writes the migration / INSERT / MERGE scripts** — validated against the real
structure of both sides.

> **Important — you run the scripts, not the tool.** The server is read-only and
> will never execute writes. It *generates* the scripts; you (or your data
> pipeline) review and run them against the target. This keeps a human in the
> loop for anything that changes data.

### 5. Ad-hoc analysis & reporting
Quick read-only questions without opening a separate client:

> *"How many open records are in each status? Give me the breakdown."*

### 6. Onboarding new developers
A new team member can ask the database questions directly — *"how do these two
tables relate?"*, *"what does this column actually contain?"* — and ramp up
without waiting on tribal knowledge.

---

## Example prompts

- "Test the oracle connection."
- "List all tables whose name contains INVOICE."
- "Describe the ORDERS table — columns, types, and primary key."
- "Show me 5 sample rows from CUSTOMERS so I understand the data."
- "Write a read-only query to find duplicate emails in the USERS table."
- "Given this mapping, generate the INSERT script to load TARGET.CLIENT from SOURCE.CUSTOMERS."

---

## The read-only safety model

`run_query` validates every statement before execution:

1. Comments (`-- ...`, `/* ... */`) and string-literal contents are stripped, so
   forbidden keywords can't be hidden inside them.
2. The statement must begin with `SELECT` or `WITH`.
3. These are rejected outright: `INSERT`, `UPDATE`, `DELETE`, `MERGE`, `CREATE`,
   `ALTER`, `DROP`, `TRUNCATE`, `GRANT`, `REVOKE`, `COMMIT`, `ROLLBACK`,
   `BEGIN`/`DECLARE`/`CALL`/`EXECUTE` and other PL/SQL, `DBMS_*`/`UTL_*` package
   calls, `FOR UPDATE` (row locks), `SELECT ... INTO`, and any multi-statement
   input.
4. Connections are rolled back when returned to the pool.

This is enforced **in addition to** — not instead of — using a least-privilege,
read-only database account.

---

## Output format & limits

- Results return as `{ columns, rows, row_count, truncated, limit }`.
- `truncated: true` means more rows existed than the active limit — narrow the
  query or raise `ORACLE_MAX_ROWS` (mindful of volume).
- Value handling: `DATE`/`TIMESTAMP` → ISO strings; numbers preserved (integers
  stay exact); `CLOB` text truncated past ~4000 chars with a marker; `BLOB`/raw
  bytes summarized as a length + hex preview rather than dumped.

---

## Good practices

- Connect with a **read-only** account.
- Keep `ORACLE_MAX_ROWS` modest; use `WHERE` and bind variables to scope
  queries instead of pulling whole tables.
- For migrations, **review generated scripts** before running them, and run
  them through your own controlled process — never blindly.
