"""Static check that a query is a single read-only SELECT/WITH statement (SPEC 5.3, item 2).

This is the second line of defence. The first is the `mode=ro` connection in `executor.py`, so a
bug here is bounded by it. The check works on a "skeleton" of the SQL with comments blanked and
quoted text replaced by a placeholder, so a keyword inside a string, comment or quoted identifier
neither triggers a rejection nor hides one.
"""

from __future__ import annotations

import re

from askdb.errors import UnsafeSQLError

_ALLOWED_FIRST_WORDS = {"select", "with"}

# A WITH clause can prefix INSERT, UPDATE and DELETE, so these are rejected anywhere in the query.
_FORBIDDEN_WORDS = {
    "insert",
    "update",
    "delete",
    "drop",
    "create",
    "alter",
    "attach",
    "detach",
    "pragma",
    "vacuum",
    "reindex",
    "analyze",
    "load_extension",
}

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _skip_quoted(sql: str, start: int, quote: str) -> int:
    """Return the index just past the quoted text that opens at `start` (doubled quotes escape)."""
    i = start + 1
    while i < len(sql):
        if sql[i] == quote:
            if sql[i + 1 : i + 2] == quote:
                i += 2
                continue
            return i + 1
        i += 1
    return len(sql)


def _skeleton(sql: str) -> str:
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        pair = sql[i : i + 2]
        if pair == "--":
            end = sql.find("\n", i)
            i = n if end == -1 else end
            out.append(" ")
        elif pair == "/*":
            end = sql.find("*/", i + 2)
            i = n if end == -1 else end + 2
            out.append(" ")
        elif c in "'\"`":
            i = _skip_quoted(sql, i, c)
            out.append("?")
        elif c == "[":
            end = sql.find("]", i)
            i = n if end == -1 else end + 1
            out.append("?")
        else:
            out.append(c)
            i += 1
    return "".join(out)


def validate_sql(sql: str) -> str:
    """Return the statement to run, or raise `UnsafeSQLError` if it is not a lone SELECT/WITH."""
    text = _skeleton(sql).strip().rstrip(";").rstrip()
    if not text:
        raise UnsafeSQLError("The query is empty.")
    if ";" in text:
        raise UnsafeSQLError("Only a single query can be run at a time.")

    words = [w.lower() for w in _WORD.findall(text)]
    if not words or words[0] not in _ALLOWED_FIRST_WORDS:
        raise UnsafeSQLError("Only SELECT queries are allowed; AskDB is read-only.")
    for word in words:
        if word in _FORBIDDEN_WORDS:
            raise UnsafeSQLError(f"{word.upper()} is not allowed; AskDB is read-only.")
    if ("replace", "into") in zip(words, words[1:], strict=False):
        raise UnsafeSQLError("REPLACE is not allowed; AskDB is read-only.")
    return sql.strip()
