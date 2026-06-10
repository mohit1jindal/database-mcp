"""Configuration loaded from environment variables.

Credentials are NEVER hardcoded and NEVER logged. The target database is
selected with DB_TYPE; connection details come either as discrete components
(DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME) or as a full DATABASE_URL.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy import URL

# Map a friendly DB_TYPE to a SQLAlchemy "dialect+driver" string.
DRIVERS: dict[str, str] = {
    "oracle": "oracle+oracledb",
    "postgresql": "postgresql+psycopg2",
    "postgres": "postgresql+psycopg2",
    "mysql": "mysql+pymysql",
    "mariadb": "mysql+pymysql",
    "mssql": "mssql+pyodbc",
    "sqlserver": "mssql+pyodbc",
    "sqlite": "sqlite",
}

DEFAULT_PORTS: dict[str, int] = {
    "oracle": 1521,
    "postgresql": 5432,
    "postgres": 5432,
    "mysql": 3306,
    "mariadb": 3306,
    "mssql": 1433,
    "sqlserver": 1433,
}

SUPPORTED = sorted(set(DRIVERS))


@dataclass(frozen=True)
class Config:
    db_type: str
    url: str               # SQLAlchemy URL string (password may be embedded)
    max_rows: int
    query_timeout_s: int
    pool_min: int
    pool_max: int


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be an integer, got {raw!r}") from exc


def _build_url(db_type: str) -> URL:
    """Build a SQLAlchemy URL from component environment variables."""
    user = os.environ.get("DB_USER")
    password = os.environ.get("DB_PASSWORD")
    host = os.environ.get("DB_HOST")
    name = os.environ.get("DB_NAME")  # database / service name / file path
    port_raw = os.environ.get("DB_PORT")
    port = int(port_raw) if port_raw else DEFAULT_PORTS.get(db_type)

    drivername = DRIVERS[db_type]

    if db_type == "sqlite":
        # DB_NAME is the file path; empty -> in-memory.
        return URL.create("sqlite", database=name or "")

    missing = [n for n, v in (("DB_HOST", host), ("DB_USER", user), ("DB_PASSWORD", password)) if not v]
    if missing:
        raise RuntimeError(
            "Missing required environment variable(s) for DB_TYPE="
            f"{db_type}: {', '.join(missing)}. "
            "Provide them, or set DATABASE_URL with a full SQLAlchemy URL."
        )

    if db_type == "oracle":
        # Oracle: connect by service name (thin mode).
        query = {"service_name": name} if name else {}
        return URL.create(drivername, username=user, password=password, host=host, port=port, query=query)

    if db_type in ("mssql", "sqlserver"):
        # SQL Server via pyodbc needs an ODBC driver name.
        odbc = os.environ.get("DB_ODBC_DRIVER", "ODBC Driver 17 for SQL Server")
        return URL.create(
            drivername, username=user, password=password, host=host, port=port,
            database=name, query={"driver": odbc},
        )

    # postgresql / mysql / mariadb
    return URL.create(drivername, username=user, password=password, host=host, port=port, database=name)


def load_config() -> Config:
    """Read and validate connection settings from the environment."""
    explicit_url = os.environ.get("DATABASE_URL")
    db_type = (os.environ.get("DB_TYPE") or "").strip().lower()

    if explicit_url:
        # Infer db_type from the URL if not given (best effort, for messaging).
        if not db_type:
            db_type = explicit_url.split(":", 1)[0].split("+", 1)[0]
        url_str = explicit_url
    else:
        if not db_type:
            raise RuntimeError(
                "DB_TYPE is required (one of: " + ", ".join(SUPPORTED) + "). "
                "Alternatively set DATABASE_URL with a full SQLAlchemy URL."
            )
        if db_type not in DRIVERS:
            raise RuntimeError(
                f"Unsupported DB_TYPE={db_type!r}. Supported: {', '.join(SUPPORTED)}."
            )
        url_str = _build_url(db_type).render_as_string(hide_password=False)

    return Config(
        db_type=db_type,
        url=url_str,
        max_rows=_int_env("DB_MAX_ROWS", 100),
        query_timeout_s=_int_env("DB_QUERY_TIMEOUT", 30),
        pool_min=_int_env("DB_POOL_MIN", 1),
        pool_max=_int_env("DB_POOL_MAX", 5),
    )
