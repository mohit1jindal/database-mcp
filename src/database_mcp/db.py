"""Database connectivity via SQLAlchemy (multi-dialect, read-only use).

A single Engine is created lazily on first use from environment config. Queries
run inside a transaction that is always rolled back, so the server can never
commit a change even if a write somehow slipped past the safety layer.

Schema discovery uses SQLAlchemy's cross-dialect Inspector, so list_schemas /
list_tables / describe_table work the same across Oracle, PostgreSQL, MySQL,
SQL Server, and SQLite.
"""

from __future__ import annotations

import datetime
import decimal
import threading

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from .config import Config, load_config

_engine: Engine | None = None
_engine_lock = threading.Lock()
_config: Config | None = None

# Truncation caps for oversized cell values (keeps tool output bounded).
_MAX_TEXT = 4000
_MAX_BYTES_PREVIEW = 64

# Friendly hints when an optional driver isn't installed.
_DRIVER_HINTS = {
    "psycopg2": "pip install \"database-mcp[postgresql]\"",
    "pymysql": "pip install \"database-mcp[mysql]\"",
    "pyodbc": "pip install \"database-mcp[mssql]\"",
}


def _get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                cfg = _get_config()
                kwargs: dict = {"pool_pre_ping": True}
                if cfg.db_type != "sqlite":
                    kwargs["pool_size"] = cfg.pool_min or 1
                    kwargs["max_overflow"] = max(0, cfg.pool_max - (cfg.pool_min or 1))
                try:
                    _engine = create_engine(cfg.url, **kwargs)
                except ModuleNotFoundError as exc:  # missing optional driver
                    name = getattr(exc, "name", "") or str(exc)
                    for mod, hint in _DRIVER_HINTS.items():
                        if mod in name:
                            raise RuntimeError(
                                f"Database driver '{mod}' is not installed. Install it with: {hint}"
                            ) from exc
                    raise
    return _engine


def _convert(value):
    """Make a single fetched value JSON-serializable and bounded in size."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return str(value)
    if isinstance(value, decimal.Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        b = bytes(value)
        preview = b[:_MAX_BYTES_PREVIEW].hex()
        suffix = "..." if len(b) > _MAX_BYTES_PREVIEW else ""
        return f"<{len(b)} bytes: {preview}{suffix}>"
    if isinstance(value, str) and len(value) > _MAX_TEXT:
        return value[:_MAX_TEXT] + f"... <truncated, {len(value)} chars total>"
    return value


def run_query(sql: str, binds: dict | None = None, max_rows: int | None = None) -> dict:
    """Execute a query and return columns + rows.

    Row count is capped at DB_MAX_ROWS (default 100). A caller-supplied
    *max_rows* may only lower the cap, never raise it past the env ceiling.
    The transaction is always rolled back.
    """
    cfg = _get_config()
    ceiling = cfg.max_rows
    limit = ceiling if not max_rows else min(int(max_rows), ceiling)

    engine = get_engine()
    with engine.connect() as conn:
        try:
            result = conn.execute(text(sql), binds or {})
            if not result.returns_rows:
                return {"columns": [], "rows": [], "row_count": 0, "truncated": False, "limit": limit}
            columns = list(result.keys())
            raw = result.fetchmany(limit)
            truncated = len(raw) == limit and result.fetchone() is not None
            rows = [
                {col: _convert(val) for col, val in zip(columns, record)}
                for record in raw
            ]
        finally:
            conn.rollback()
    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "limit": limit,
    }


def db_info() -> dict:
    """Return dialect + server version to confirm connectivity."""
    engine = get_engine()
    with engine.connect() as conn:
        version = ".".join(str(p) for p in (conn.dialect.server_version_info or [])) or "unknown"
        return {
            "connected": True,
            "dialect": engine.dialect.name,
            "driver": engine.dialect.driver,
            "server_version": version,
        }


def list_schemas() -> dict:
    insp = inspect(get_engine())
    return {"schemas": insp.get_schema_names()}


def _target_schemas(insp, schema: str | None) -> list[str | None]:
    if schema and schema != "*":
        return [schema]
    if schema == "*":
        return list(insp.get_schema_names())
    # Default to the connection's default schema (None for SQLite).
    return [insp.default_schema_name]


def list_tables(schema: str | None = None, name_like: str | None = None) -> dict:
    insp = inspect(get_engine())
    needle = name_like.lower() if name_like else None
    out: list[dict] = []
    for sch in _target_schemas(insp, schema):
        try:
            names = insp.get_table_names(schema=sch) + insp.get_view_names(schema=sch)
        except Exception:
            continue
        for tname in names:
            if needle and needle not in tname.lower():
                continue
            out.append({"schema": sch, "name": tname})
    return {"tables": out, "table_count": len(out)}


def describe_table(table_name: str, schema: str | None = None) -> dict:
    insp = inspect(get_engine())
    columns = []
    for col in insp.get_columns(table_name, schema=schema):
        columns.append({
            "name": col.get("name"),
            "type": str(col.get("type")),
            "nullable": col.get("nullable"),
            "default": col.get("default"),
        })
    try:
        pk = insp.get_pk_constraint(table_name, schema=schema).get("constrained_columns", [])
    except Exception:
        pk = []
    return {
        "table": table_name,
        "schema": schema,
        "columns": columns,
        "primary_key": pk,
    }
