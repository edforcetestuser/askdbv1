import sqlite3
import time

import pytest

from askdb.config import Settings
from askdb.errors import DatabaseBusy, QueryFailed, QueryTimeout, UnsafeSQLError
from askdb.executor import connect_readonly, run_query

WRITE_ATTEMPTS = {
    "insert": "INSERT INTO customers (company_name) VALUES ('x')",
    "update": "UPDATE invoices SET status = 'paid'",
    "delete": "DELETE FROM invoices",
    "drop": "DROP TABLE invoices",
    "attach": "ATTACH DATABASE 'other.db' AS other",
    "pragma": "PRAGMA writable_schema = ON",
    "multi-statement": "SELECT 1; DELETE FROM invoices",
    "cte delete": "WITH x AS (SELECT 1) DELETE FROM invoices",
}


def listing(path):
    return sorted(p.name for p in path.parent.iterdir())


def test_select_returns_columns_and_rows(db_path, settings):
    result = run_query(
        db_path,
        "SELECT SUM(mrr) AS total_mrr FROM subscriptions WHERE status = 'active'",
        settings,
    )
    assert result.columns == ["total_mrr"]
    assert result.row_count == 1
    assert result.rows[0][0] > 0
    assert result.truncated is False


def test_with_query_works(db_path, settings):
    result = run_query(
        db_path,
        "WITH active AS (SELECT * FROM subscriptions WHERE status = 'active') "
        "SELECT COUNT(*) AS n FROM active;",
        settings,
    )
    assert result.columns == ["n"]
    assert result.rows[0][0] > 0


def test_result_with_no_rows_keeps_its_columns(db_path, settings):
    result = run_query(db_path, "SELECT company_name FROM customers WHERE 1 = 0", settings)
    assert result.columns == ["company_name"]
    assert result.rows == []
    assert result.truncated is False


def test_more_than_the_row_cap_is_truncated_and_flagged(db_path, settings):
    total = run_query(db_path, "SELECT COUNT(*) FROM invoices", settings).rows[0][0]
    assert total > 1000

    result = run_query(db_path, "SELECT * FROM invoices", settings)
    assert result.row_count == 1000
    assert result.truncated is True


def test_exactly_the_row_cap_is_not_flagged(db_path):
    settings = Settings(row_cap=5)
    result = run_query(db_path, "SELECT * FROM plans", settings)  # 4 plans
    assert result.truncated is False

    result = run_query(db_path, "SELECT * FROM customers LIMIT 5", settings)
    assert result.row_count == 5
    assert result.truncated is False

    result = run_query(db_path, "SELECT * FROM customers LIMIT 6", settings)
    assert result.row_count == 5
    assert result.truncated is True


@pytest.mark.parametrize("sql", WRITE_ATTEMPTS.values(), ids=WRITE_ATTEMPTS.keys())
def test_write_attempts_are_rejected_and_the_database_is_unchanged(
    db_path, settings, sha256, sql
):
    before_hash, before_files = sha256(db_path), listing(db_path)

    with pytest.raises(UnsafeSQLError):
        run_query(db_path, sql, settings)

    assert sha256(db_path) == before_hash
    assert listing(db_path) == before_files


def test_read_only_connection_blocks_writes_even_without_the_guard(db_path, settings, sha256):
    before_hash, before_files = sha256(db_path), listing(db_path)
    conn = connect_readonly(db_path, settings)
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM invoices")
        # mode=ro must hold even if the extra query_only guard is switched off.
        conn.execute("PRAGMA query_only = OFF")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM invoices")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("CREATE TABLE sneaky (a INTEGER)")
    finally:
        conn.close()

    assert sha256(db_path) == before_hash
    assert listing(db_path) == before_files


def test_missing_database_fails_without_creating_the_file(tmp_path, settings):
    missing = tmp_path / "nope.db"
    with pytest.raises(QueryFailed):
        run_query(missing, "SELECT 1", settings)
    assert not missing.exists()


def test_non_sqlite_file_fails_cleanly(tmp_path, settings):
    not_a_db = tmp_path / "notes.db"
    not_a_db.write_text("this is not a database, just a long line of text " * 50)
    with pytest.raises(QueryFailed):
        run_query(not_a_db, "SELECT * FROM t", settings)


def test_sql_errors_keep_the_raw_text_out_of_the_user_message(db_path, settings):
    with pytest.raises(QueryFailed) as info:
        run_query(db_path, "SELECT * FROM no_such_table", settings)
    assert "no_such_table" in info.value.detail
    assert "no_such_table" not in info.value.user_message
    assert "no such table" not in info.value.user_message


def test_runaway_cross_join_is_aborted_and_the_next_query_still_works(db_path):
    settings = Settings(query_timeout_seconds=0.3)
    cross_join = "SELECT COUNT(*) FROM invoices a, invoices b, invoices c, invoices d"

    started = time.monotonic()
    with pytest.raises(QueryTimeout) as info:
        run_query(db_path, cross_join, settings)
    elapsed = time.monotonic() - started

    assert elapsed < 3
    assert "too long" in info.value.user_message
    assert run_query(db_path, "SELECT 1", settings).rows == [(1,)]


def test_locked_database_gives_a_friendly_busy_error(db_path, sha256):
    # In rollback-journal mode an exclusive lock blocks readers; WAL would not.
    writer = sqlite3.connect(db_path, isolation_level=None)
    writer.execute("PRAGMA journal_mode = DELETE")
    before_hash = sha256(db_path)
    writer.execute("BEGIN EXCLUSIVE")
    try:
        settings = Settings(busy_timeout_ms=50)
        with pytest.raises(DatabaseBusy) as info:
            run_query(db_path, "SELECT COUNT(*) FROM customers", settings)
        assert "busy" in info.value.user_message
        assert "locked" not in info.value.user_message
    finally:
        writer.execute("ROLLBACK")
        writer.close()

    assert sha256(db_path) == before_hash
    assert run_query(db_path, "SELECT COUNT(*) FROM customers", Settings()).rows[0][0] > 0
