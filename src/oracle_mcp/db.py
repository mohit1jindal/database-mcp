"""Oracle connectivity via python-oracledb in thin mode (no Oracle client install).

A small connection pool is created lazily on first use from environment
config, so the server process can start (and be registered) even before
credentials are present. Connections are always rolled back on release as a
belt-and-suspenders guard against any accidental open transaction.
"""

from __future__ import annotations

import datetime
import decimal
import threading

import oracledb

from .config import Config, load_config

# Return CLOB/BLOB content directly as str/bytes instead of LOB locators —
# simpler and avoids streaming reads after the cursor closes.
oracledb.defaults.fetch_lobs = False

_pool: "oracledb.ConnectionPool | None" = None
_pool_lock = threading.Lock()
_config: Config | None = None

# Truncation caps for oversized cell values (keeps tool output bounded).
_MAX_TEXT = 4000
_MAX_BYTES_PREVIEW = 64


def _get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_pool() -> "oracledb.ConnectionPool":
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                cfg = _get_config()
                kwargs = dict(
                    user=cfg.user,
                    password=cfg.password,
                    dsn=cfg.dsn,
                    min=cfg.pool_min,
                    max=cfg.pool_max,
                    increment=1,
                )
                if cfg.config_dir:
                    kwargs["config_dir"] = cfg.config_dir
                if cfg.wallet_location:
                    kwargs["wallet_location"] = cfg.wallet_location
                if cfg.wallet_password:
                    kwargs["wallet_password"] = cfg.wallet_password
                _pool = oracledb.create_pool(**kwargs)
    return _pool


def _convert(value):
    """Make a single fetched value JSON-serializable and bounded in size."""
    if value is None:
        return None
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, datetime.timedelta):
        return str(value)
    if isinstance(value, decimal.Decimal):
        # Preserve integers exactly; floats are fine for exploration.
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, bytes):
        preview = value[:_MAX_BYTES_PREVIEW].hex()
        suffix = "..." if len(value) > _MAX_BYTES_PREVIEW else ""
        return f"<{len(value)} bytes: {preview}{suffix}>"
    if isinstance(value, str) and len(value) > _MAX_TEXT:
        return value[:_MAX_TEXT] + f"... <truncated, {len(value)} chars total>"
    return value


def run_query(sql: str, binds: dict | None = None, max_rows: int | None = None) -> dict:
    """Execute a query and return columns + rows.

    Row count is capped at ORACLE_MAX_ROWS (default 100). A caller-supplied
    *max_rows* may only lower the cap, never raise it past the env ceiling.
    """
    cfg = _get_config()
    ceiling = cfg.max_rows
    limit = ceiling if not max_rows else min(int(max_rows), ceiling)

    pool = get_pool()
    conn = pool.acquire()
    try:
        try:
            conn.call_timeout = cfg.query_timeout_s * 1000
        except Exception:
            pass  # call_timeout unsupported on this driver/build — non-fatal
        with conn.cursor() as cur:
            cur.execute(sql, binds or {})
            if cur.description is None:
                return {"columns": [], "rows": [], "row_count": 0, "truncated": False, "limit": limit}
            columns = [d[0] for d in cur.description]
            raw = cur.fetchmany(limit)
            truncated = len(raw) == limit and cur.fetchone() is not None
            rows = [
                {col: _convert(val) for col, val in zip(columns, record)}
                for record in raw
            ]
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
            "limit": limit,
        }
    finally:
        try:
            conn.rollback()
        except Exception:
            pass
        pool.release(conn)


def db_version() -> str:
    pool = get_pool()
    conn = pool.acquire()
    try:
        return conn.version
    finally:
        pool.release(conn)
