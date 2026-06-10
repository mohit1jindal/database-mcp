"""Configuration loaded from environment variables.

Credentials are NEVER hardcoded and NEVER logged. All connection settings
come from the environment so the server can be pointed at any Oracle instance
without code changes and without secrets touching disk in this repo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    user: str
    password: str
    dsn: str
    config_dir: str | None
    wallet_location: str | None
    wallet_password: str | None
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


def load_config() -> Config:
    """Read and validate connection settings from the environment.

    Required: ORACLE_USER, ORACLE_PASSWORD, ORACLE_DSN
    DSN forms accepted by python-oracledb thin mode, e.g.:
      - host:port/service_name
      - an Easy Connect string
      - a tnsnames.ora alias (set ORACLE_CONFIG_DIR to its directory)
    """
    user = os.environ.get("ORACLE_USER")
    password = os.environ.get("ORACLE_PASSWORD")
    dsn = os.environ.get("ORACLE_DSN")

    missing = [n for n, v in (
        ("ORACLE_USER", user),
        ("ORACLE_PASSWORD", password),
        ("ORACLE_DSN", dsn),
    ) if not v]
    if missing:
        raise RuntimeError(
            "Missing required environment variable(s): "
            + ", ".join(missing)
            + ". Set them in your MCP server config or shell — never hardcode credentials."
        )

    return Config(
        user=user,
        password=password,
        dsn=dsn,
        config_dir=os.environ.get("ORACLE_CONFIG_DIR") or None,
        wallet_location=os.environ.get("ORACLE_WALLET_LOCATION") or None,
        wallet_password=os.environ.get("ORACLE_WALLET_PASSWORD") or None,
        max_rows=_int_env("ORACLE_MAX_ROWS", 100),
        query_timeout_s=_int_env("ORACLE_QUERY_TIMEOUT", 30),
        pool_min=_int_env("ORACLE_POOL_MIN", 1),
        pool_max=_int_env("ORACLE_POOL_MAX", 4),
    )
