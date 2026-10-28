"""Errors raised on the query path.

`user_message` is plain English and safe to show to users. `detail` is the raw text (for example
SQLite's own message) and belongs in the audit log and in the model's retry prompt, never in a
response to the user.
"""

from __future__ import annotations


class QueryError(Exception):
    def __init__(self, user_message: str, detail: str = "") -> None:
        super().__init__(detail or user_message)
        self.user_message = user_message
        self.detail = detail or user_message


class UnsafeSQLError(QueryError):
    """The statement is not a single read-only SELECT/WITH query."""


class QueryTimeout(QueryError):
    """The query ran past the configured time limit and was aborted."""


class DatabaseBusy(QueryError):
    """The database stayed locked by another process for longer than the busy timeout."""


class QueryFailed(QueryError):
    """SQLite rejected or could not run the query (bad SQL, unreadable file, ...)."""
