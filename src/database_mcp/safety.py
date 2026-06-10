"""Read-only SQL enforcement.

The server must never modify data. We enforce this defensively at the tool
layer (in addition to recommending a read-only DB account):

  * The statement must START with SELECT, WITH, or EXPLAIN. This alone blocks
    every standalone DDL/DML statement (INSERT/UPDATE/CREATE/DROP/GRANT/...).
  * Only a single statement is allowed (no piggy-backed second statement).
  * A small set of constructs that can hide a write *inside* a SELECT/WITH
    statement are rejected: data-modifying CTEs (INSERT/UPDATE/DELETE/MERGE),
    `SELECT ... INTO` (creates a table on some engines), and `FOR UPDATE`
    (row locks).

Comments and string literals are stripped before inspection so keywords can't
be smuggled in via a comment or quoted text. Crucially, we do NOT blanket-ban
common words like COMMENT, SET, or LOCK that frequently appear as column names
— the start-keyword + single-statement checks already make those harmless.
"""

from __future__ import annotations

import re

__all__ = ["ensure_read_only", "ReadOnlyViolation"]


class ReadOnlyViolation(ValueError):
    """Raised when a statement is not a safe read-only query."""


# Permitted leading keywords. EXPLAIN is read-only plan inspection; even
# `EXPLAIN ANALYZE` only executes the (read-only) SELECT it wraps, and any
# write it tried to wrap would be caught by the in-statement scan below.
_ALLOWED_START = {"SELECT", "WITH", "EXPLAIN"}

# Tokens that must never appear ANYWHERE in the statement, because they can
# embed a write inside an otherwise SELECT/WITH-leading statement (e.g. a
# data-modifying CTE in PostgreSQL: WITH x AS (DELETE ... RETURNING ...) ...).
# These are real SQL verbs, not common column names, so whole-word matching
# them is safe. PL/SQL package prefixes are matched as prefixes.
_FORBIDDEN_WORDS = {
    "INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT",
    "CREATE", "ALTER", "DROP", "TRUNCATE",
    "GRANT", "REVOKE", "CALL",
    "INTO",  # blocks `SELECT ... INTO new_table` (a write on T-SQL / Postgres)
}
_FORBIDDEN_PREFIXES = ("DBMS_", "UTL_", "OWA_")  # Oracle PL/SQL packages

_TRAILING_SEMI = re.compile(r";\s*$")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_STRING_LITERAL = re.compile(r"'(?:''|[^'])*'")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_$#]*")
_FOR_UPDATE = re.compile(r"\bFOR\s+UPDATE\b")


def _strip(sql: str) -> str:
    """Remove comments and string-literal contents for safe token inspection."""
    sql = _BLOCK_COMMENT.sub(" ", sql)
    sql = _LINE_COMMENT.sub(" ", sql)
    sql = _STRING_LITERAL.sub("''", sql)
    return sql


def ensure_read_only(sql: str) -> None:
    """Validate that *sql* is a single read-only statement.

    Raises ReadOnlyViolation otherwise.
    """
    if not sql or not sql.strip():
        raise ReadOnlyViolation("Empty query.")

    stripped = _strip(sql).strip()
    # Drop one optional trailing semicolon, then reject any remaining one.
    stripped = _TRAILING_SEMI.sub("", stripped).strip()
    if ";" in stripped:
        raise ReadOnlyViolation(
            "Multiple statements are not allowed; submit a single read-only query."
        )

    first = _WORD.search(stripped)
    first_kw = first.group(0).upper() if first else None
    if first_kw not in _ALLOWED_START:
        raise ReadOnlyViolation(
            f"Only SELECT / WITH / EXPLAIN queries are allowed (got '{first_kw or '?'}'). "
            "This server is read-only."
        )

    upper = stripped.upper()
    for token in _FORBIDDEN_WORDS:
        if re.search(r"\b" + re.escape(token) + r"\b", upper):
            raise ReadOnlyViolation(
                f"Disallowed keyword '{token}' — this server only reads data."
            )
    for prefix in _FORBIDDEN_PREFIXES:
        if re.search(r"\b" + re.escape(prefix), upper):
            raise ReadOnlyViolation(
                f"Disallowed PL/SQL package reference '{prefix}*' in query."
            )

    if _FOR_UPDATE.search(upper):
        raise ReadOnlyViolation("'FOR UPDATE' is not allowed (acquires row locks).")
