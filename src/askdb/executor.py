"""The only code path that touches a target database (SPEC 5.3).

Every query gets its own `mode=ro` connection, a time limit enforced by a progress handler, and a
row cap. Nothing here ever writes to the target.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from askdb.config import Settings
from askdb.errors import DatabaseBusy, QueryFailed, QueryTimeout
from askdb.sql_guard import validate_sql

log = logging.getLogger(__name__)

# SQLite calls the progress handler once per this many virtual-machine instructions.
_PROGRESS_INTERVAL = 10_000


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool

    @property
    def row_count(self) -> int:
        return len(self.rows)


def connect_readonly(db_path: str | Path, settings: Settings) -> sqlite3.Connection:
    """Open a fresh read-only connection. Connections are never shared across queries."""
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=settings.busy_timeout_ms / 1000)
    # Belt and braces on top of mode=ro; mode=ro stays the guarantee if this is ever switched off.
    conn.execute("PRAGMA query_only = ON")
    return conn


def _translate(exc: sqlite3.Error, timed_out: bool) -> Exception:
    detail = str(exc)
    if timed_out:
        return QueryTimeout(
            "That question took too long to work out. Try narrowing it, for example to a "
            "date range.",
            detail,
        )
    if isinstance(exc, sqlite3.OperationalError) and ("locked" in detail or "busy" in detail):
        return DatabaseBusy("The database is busy right now. Please try again in a moment.", detail)
    return QueryFailed("The query could not be run.", detail)


def run_query(db_path: str | Path, sql: str, settings: Settings) -> QueryResult:
    """Run one read-only query and return at most `settings.row_cap` rows.

    Raises `UnsafeSQLError` for anything but a single SELECT/WITH, `QueryTimeout` when the time
    limit is hit, `DatabaseBusy` when another process holds the lock, and `QueryFailed` otherwise.
    """
    statement = validate_sql(sql)
    deadline = time.monotonic() + settings.query_timeout_seconds
    timed_out = False

    def abort_when_late() -> int:
        nonlocal timed_out
        if time.monotonic() > deadline:
            timed_out = True
            return 1
        return 0

    conn: sqlite3.Connection | None = None
    try:
        conn = connect_readonly(db_path, settings)
        conn.set_progress_handler(abort_when_late, _PROGRESS_INTERVAL)
        cursor = conn.execute(statement)
        columns = [d[0] for d in cursor.description or []]
        fetched = cursor.fetchmany(settings.row_cap + 1)
    except sqlite3.Error as exc:
        error = _translate(exc, timed_out)
        log.warning("query failed: %s", error)
        raise error from exc
    finally:
        if conn is not None:
            conn.close()

    truncated = len(fetched) > settings.row_cap
    return QueryResult(columns=columns, rows=fetched[: settings.row_cap], truncated=truncated)
