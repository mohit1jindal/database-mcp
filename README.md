# oracle-mcp

A **local** MCP server that exposes a read-only Oracle database to Claude Code
as native tools. Built on [FastMCP](https://github.com/jlowin/fastmcp) and
[python-oracledb](https://python-oracledb.readthedocs.io/) in **thin mode** —
no Oracle Instant Client install required.

Everything runs on your machine over stdio and query results never leave your
environment. The server is **read-only by design** and ships with no write
capability, making it safe to point at databases holding sensitive data.

## Tools

| Tool | What it does |
|------|--------------|
| `test_connection` | Verify credentials/connectivity, report Oracle version |
| `run_query` | Execute a single read-only `SELECT` / `WITH` query (supports bind variables) |
| `list_schemas` | List schemas/owners visible to the account |
| `list_tables` | List tables, filterable by owner and name substring |
| `describe_table` | Columns, types, nullability, and primary key for a table |

### Read-only guarantees

1. `run_query` accepts only a single `SELECT` / `WITH...SELECT` statement.
2. Comments and string literals are stripped before validation, so forbidden
   keywords can't be smuggled in. DML, DDL, PL/SQL, `FOR UPDATE`, and
   multi-statement input are all rejected.
3. Every connection is rolled back on release.
4. Row output is capped by `ORACLE_MAX_ROWS` (default 100).

> **Defense in depth:** still connect with a database account that only has
> `SELECT` privileges. The tool-layer checks are a safety net, not a substitute
> for least-privilege credentials.

## Setup

```powershell
cd path\to\oracle-mcp
uv venv
uv pip install -e .
```

Credentials are read from the environment — **never hardcoded**. Copy the
example and fill it in (the `.env` file is git-ignored):

```powershell
Copy-Item .env.example .env
# then edit .env
```

Required variables: `ORACLE_USER`, `ORACLE_PASSWORD`, `ORACLE_DSN`
(e.g. `host:1521/service_name`). See [.env.example](.env.example) for
TLS/wallet and tuning options.

## Register with Claude Code

Point Claude Code at the venv's Python so dependencies resolve. The cleanest
way is to put the credentials in the MCP server config's `env` block rather
than a shell `.env`:

```powershell
claude mcp add oracle `
  --env ORACLE_USER=your_readonly_user `
  --env ORACLE_PASSWORD=your_password `
  --env ORACLE_DSN=host:1521/service_name `
  --env ORACLE_MAX_ROWS=100 `
  -- "path\to\oracle-mcp\.venv\Scripts\python.exe" -m oracle_mcp.server
```

Or add it to `.mcp.json` / your Claude Code settings manually:

```json
{
  "mcpServers": {
    "oracle": {
      "command": "path\\to\\oracle-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "oracle_mcp.server"],
      "env": {
        "ORACLE_USER": "your_readonly_user",
        "ORACLE_PASSWORD": "your_password",
        "ORACLE_DSN": "host:1521/service_name",
        "ORACLE_MAX_ROWS": "100"
      }
    }
  }
}
```

Restart Claude Code, then run `/mcp` to confirm the `oracle` server is
connected. Try: *"test the oracle connection"*, then *"list tables matching
INVOICE in schema X"*.

## Local smoke test (no DB needed)

```powershell
uv run python -c "from oracle_mcp.safety import ensure_read_only; ensure_read_only('SELECT 1 FROM dual'); print('ok')"
```

## Documentation

- [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — end-to-end setup: prerequisites, install, env vars, Claude Code registration, multiple databases, TLS/wallet, verification, and troubleshooting.
- [docs/USE_CASES.md](docs/USE_CASES.md) — features, full tool reference, workflows (schema discovery, mapping, writing/debugging SQL, source→target migration), example prompts, and the read-only safety model.

## Project layout

```
src/oracle_mcp/
  config.py    env-var configuration (no hardcoded secrets)
  db.py        thin-mode connection pool + value conversion
  safety.py    read-only SQL enforcement
  server.py    FastMCP tools + entry point
docs/
  CONFIGURATION.md
  USE_CASES.md
```
