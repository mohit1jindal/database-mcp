# Configuration Guide — end to end

This guide walks through everything from a clean machine to a working
`oracle-mcp` server registered in Claude Code, including connecting multiple
databases, TLS/wallet setups, verification, and troubleshooting.

> The server is **read-only**. It never writes to your database. Even so, the
> recommended practice is to connect with a database account that only has
> `SELECT` privileges (defense in depth).

---

## 1. Prerequisites

| Requirement | Notes |
|-------------|-------|
| **Python 3.10+** | `python --version` |
| **[uv](https://docs.astral.sh/uv/)** | Used for the virtual environment and installs. `uv --version` |
| **Network access to the Oracle DB** | The machine running the server must be able to reach the DB host/port (default 1521). |
| **A database account** | Ideally read-only (`SELECT`-only). You need the username, password, host, port, and service name. |
| **An MCP client** | e.g. Claude Code. |

You do **not** need the Oracle Instant Client — `python-oracledb` runs in
**thin mode** (pure Python).

---

## 2. Install

```powershell
# from wherever you keep projects
git clone https://github.com/mohit1jindal/oracle-mcp.git
cd oracle-mcp

uv venv
uv pip install -e .
```

This creates a `.venv` and installs the server plus its dependencies
(`oracledb`, `fastmcp`).

---

## 3. Connection settings (environment variables)

All configuration comes from environment variables — **nothing is hardcoded**,
and no secrets are stored in the repository.

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `ORACLE_USER` | Database username | `app_readonly` |
| `ORACLE_PASSWORD` | Password for that user | *(set via your secret mechanism)* |
| `ORACLE_DSN` | Connection target | `db-host.example.com:1521/ORCLPDB1` |

`ORACLE_DSN` accepts any form python-oracledb thin mode understands:

- **Easy Connect:** `host:port/service_name` (most common)
- **Easy Connect Plus:** `tcps://host:port/service?...` (TLS)
- **A tnsnames.ora alias:** set `ORACLE_CONFIG_DIR` to the directory holding `tnsnames.ora`

### Optional — TLS / wallet (Oracle Cloud, mTLS)

| Variable | Description |
|----------|-------------|
| `ORACLE_CONFIG_DIR` | Directory containing `tnsnames.ora` / `sqlnet.ora` |
| `ORACLE_WALLET_LOCATION` | Path to the wallet directory |
| `ORACLE_WALLET_PASSWORD` | Wallet password, if the wallet is encrypted |

### Optional — safety / performance knobs

| Variable | Default | Description |
|----------|---------|-------------|
| `ORACLE_MAX_ROWS` | `100` | Hard ceiling on rows returned by any query. A per-call `max_rows` can only lower this, never raise it. |
| `ORACLE_QUERY_TIMEOUT` | `30` | Seconds before a running query is cancelled. |
| `ORACLE_POOL_MIN` | `1` | Minimum pooled connections. |
| `ORACLE_POOL_MAX` | `4` | Maximum pooled connections. |

### Where to put them

Two options:

1. **In the MCP client config's `env` block** (recommended — see §4). Keeps it
   scoped to the server process.
2. **In a local `.env`** for manual runs / testing:
   ```powershell
   Copy-Item .env.example .env
   # edit .env — it is git-ignored
   ```

**Never commit real credentials.** `.env`, wallets, and key files are excluded
by `.gitignore`.

---

## 4. Register with Claude Code

Point the client at the venv's Python so dependencies resolve. Use `--scope user`
to make it available across all your projects (omit it for the current project
only).

```powershell
claude mcp add oracle --scope user `
  --env ORACLE_USER=app_readonly `
  --env ORACLE_PASSWORD=your_password `
  --env ORACLE_DSN=db-host.example.com:1521/ORCLPDB1 `
  --env ORACLE_MAX_ROWS=100 `
  -- "C:\path\to\oracle-mcp\.venv\Scripts\python.exe" -m oracle_mcp.server
```

Or edit your MCP config (`.mcp.json` or the user config) directly:

```json
{
  "mcpServers": {
    "oracle": {
      "command": "C:\\path\\to\\oracle-mcp\\.venv\\Scripts\\python.exe",
      "args": ["-m", "oracle_mcp.server"],
      "env": {
        "ORACLE_USER": "app_readonly",
        "ORACLE_PASSWORD": "your_password",
        "ORACLE_DSN": "db-host.example.com:1521/ORCLPDB1",
        "ORACLE_MAX_ROWS": "100"
      }
    }
  }
}
```

Restart the client, then run `/mcp` to confirm `oracle` is **connected**.

### Keeping the password out of config

If you prefer not to store the password in the config file, omit
`ORACLE_PASSWORD` from the `env` block and set it as a user environment
variable instead — the server process inherits it:

```powershell
setx ORACLE_PASSWORD "your_password"
# then fully restart the client so it inherits the new variable
```

---

## 5. Connecting multiple databases (e.g. source + target)

The server connects to one database per instance. To work with two databases
at once — for example, reading a **source** and a **target** to generate a data
migration — register the server twice under different names with different
connection settings:

```powershell
# Source database
claude mcp add oracle_source --scope user `
  --env ORACLE_USER=src_readonly `
  --env ORACLE_PASSWORD=src_password `
  --env ORACLE_DSN=src-host.example.com:1521/SRCPDB `
  -- "C:\path\to\oracle-mcp\.venv\Scripts\python.exe" -m oracle_mcp.server

# Target database
claude mcp add oracle_target --scope user `
  --env ORACLE_USER=tgt_readonly `
  --env ORACLE_PASSWORD=tgt_password `
  --env ORACLE_DSN=tgt-host.example.com:1521/TGTPDB `
  -- "C:\path\to\oracle-mcp\.venv\Scripts\python.exe" -m oracle_mcp.server
```

Both expose the same tool set (`oracle_source__describe_table`,
`oracle_target__describe_table`, etc.), so the assistant can read structure
from both sides when generating migration scripts. (Both remain read-only — see
the use-case guide for how the migration workflow works.)

---

## 6. Verify the installation

**Offline checks (no database needed):**

```powershell
# read-only validator + tool registration
.venv\Scripts\python.exe smoke_test.py

# full MCP stdio handshake (launches the server the way the client does)
.venv\Scripts\python.exe handshake_test.py
```

**Live check (database required):** in the client, ask:

> test the oracle connection

This calls `test_connection` and should return the Oracle server version.

---

## 7. Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| `Missing required environment variable(s): ...` | One of `ORACLE_USER` / `ORACLE_PASSWORD` / `ORACLE_DSN` isn't set. If you used `setx`, fully restart the client so it inherits the variable. |
| Server shows as **failed**/disconnected in `/mcp` | Check the `command` path points at the venv's `python.exe`; confirm `uv pip install -e .` succeeded. |
| `DPY-6005` / `DPY-4011` connection errors | Host/port unreachable or the listener/service is down. Verify network access and the `service_name` in the DSN. |
| `ORA-12514` (service not known) | The service name in `ORACLE_DSN` doesn't match what the listener serves. |
| `ORA-01017` (invalid username/password) | Wrong `ORACLE_USER`/`ORACLE_PASSWORD`. |
| TLS handshake failures | Set `ORACLE_CONFIG_DIR` / `ORACLE_WALLET_LOCATION` (and `ORACLE_WALLET_PASSWORD` if encrypted). |
| Query returns `truncated: true` | The result hit `ORACLE_MAX_ROWS`. Narrow the query with `WHERE`, or raise the ceiling (mind the data volume). |
| Long-running query is cancelled | Increase `ORACLE_QUERY_TIMEOUT`, or optimize the query. |
| Errors like *"Only SELECT / WITH queries are allowed"* | Expected — the server is read-only and rejects writes/DDL/PL-SQL. |

---

## 8. Update / uninstall

```powershell
# Update to the latest code
git pull
uv pip install -e .

# Remove the registration
claude mcp remove oracle --scope user
```
