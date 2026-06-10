"""Read-only SQL enforcement.

The server must never modify data. We enforce this defensively at the tool
layer (in addition to recommending a read-only DB account): only single
SELECT / WITH...SELECT statements are allowed, and any token that could
mutate state, lock rows, or run PL/SQL is rejected.

This is a conservative allowlist-first check. It strips comments and string
literals before inspecting tokens so forbidden keywords cannot be smuggled in
via a comment or a quoted string boundary.
"""

from __future__ import annotations

import re

__all__ = ["ensure_read_only", "ReadOnlyViolation"]


class ReadOnlyViolation(ValueError):
    """Raised when a statement is not a safe read-only query."""


# Tokens that must never appear in a read-only query (matched on word
# boundaries, case-insensitive, after comments/strings are stripped).
_FORBIDDEN = {
    "INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT",
    "CREATE", "ALTER", "DROP", "TRUNCATE", "RENAME",
    "GRANT", "REVOKE", "AUDIT", "NOAUDIT",
    "COMMIT", "ROLLBACK", "SAVEPOINT", "SET",
    "LOCK", "FLASHBACK", "PURGE", "ANALYZE", "COMMENT",
    "EXEC", "EXECUTE", "CALL", "BEGIN", "DECLARE",
    "PROCEDURE", "FUNCTION", "PACKAGE", "TRIGGER",
    "DBMS_", "UTL_", "OWA_",  # PL/SQL package prefixes
    "INTO",  # blocks SELECT ... INTO (PL/SQL)
}

# A trailing semicolon is fine; anything more means multiple statements.
_TRAILING_SEMI = re.compile(r";\s*$")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_STRING_LITERAL = re.compile(r"'(?:''|[^'])*'")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_$#]*")


def _strip(sql: str) -> str:
    """Remove comments and string-literal contents for safe token inspection."""
    sql = _BLOCK_COMMENT.sub(" ", sql)
    sql = _LINE_COMMENT.sub(" ", sql)
    sql = _STRING_LITERAL.sub("''", sql)
    return sql


def ensure_read_only(sql: str) -> None:
    """Validate that *sql* is a single read-only SELECT/WITH statement.

    Raises ReadOnlyViolation otherwise.
    """
    if not sql or not sql.strip():
        raise ReadOnlyViolation("Empty query.")

    stripped = _strip(sql).strip()
    # Drop one optional trailing semicolon, then reject any remaining one.
    stripped = _TRAILING_SEMI.sub("", stripped).strip()
    if ";" in stripped:
        raise ReadOnlyViolation(
            "Multiple statements are not allowed; submit a single SELECT query."
        )

    first = (_WORD.search(stripped) or [None])
    first_kw = first.group(0).upper() if first else None
    if first_kw not in {"SELECT", "WITH"}:
        raise ReadOnlyViolation(
            f"Only SELECT / WITH queries are allowed (got '{first_kw or '?'}'). "
            "This server is read-only."
        )

    upper = stripped.upper()
    for token in _FORBIDDEN:
        if token.endswith("_"):  # package prefix, e.g. DBMS_
            if re.search(r"\b" + re.escape(token), upper):
                raise ReadOnlyViolation(
                    f"Disallowed PL/SQL package reference '{token}*' in query."
                )
            continue
        if re.search(r"\b" + re.escape(token) + r"\b", upper):
            raise ReadOnlyViolation(
                f"Disallowed keyword '{token}' in a read-only query."
            )

    # Block row-locking selects (no data change, but acquires locks).
    if re.search(r"\bFOR\s+UPDATE\b", upper):
        raise ReadOnlyViolation("'FOR UPDATE' is not allowed (acquires row locks).")
