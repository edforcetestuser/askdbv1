import pytest

from askdb.errors import UnsafeSQLError
from askdb.sql_guard import validate_sql

UNSAFE = {
    "insert": "INSERT INTO customers (company_name) VALUES ('x')",
    "update": "UPDATE invoices SET status = 'paid'",
    "delete": "DELETE FROM invoices",
    "drop table": "DROP TABLE invoices",
    "drop index": "DROP INDEX idx_invoices",
    "create": "CREATE TABLE t (a INTEGER)",
    "alter": "ALTER TABLE invoices ADD COLUMN x TEXT",
    "attach": "ATTACH DATABASE 'other.db' AS other",
    "detach": "DETACH DATABASE other",
    "pragma read": "PRAGMA table_info(invoices)",
    "pragma write": "PRAGMA writable_schema = ON",
    "vacuum": "VACUUM",
    "load_extension": "SELECT load_extension('evil')",
    "multi select": "SELECT 1; SELECT 2",
    "multi with drop": "SELECT 1; DROP TABLE invoices",
    "multi hidden by comment": "SELECT 1 /* ; */; DROP TABLE invoices",
    "cte delete": "WITH x AS (SELECT 1) DELETE FROM invoices",
    "cte insert": "WITH x AS (SELECT 1 AS a) INSERT INTO t SELECT a FROM x",
    "cte replace into": "WITH x AS (SELECT 1 AS a) REPLACE INTO t SELECT a FROM x",
    "lowercase": "drop table invoices",
    "mixed case": "dRoP TaBlE invoices",
    "comment before": "/* SELECT */ DROP TABLE invoices",
    "line comment before": "-- SELECT\nDELETE FROM invoices",
    "empty": "",
    "whitespace": "   \n ",
    "only a comment": "-- nothing here",
    "explain": "EXPLAIN SELECT 1",
    "begin": "BEGIN",
}

SAFE = {
    "simple": "SELECT 1",
    "from table": "SELECT COUNT(*) FROM invoices WHERE status = 'paid'",
    "lowercase": "select * from customers",
    "with cte": "WITH a AS (SELECT 1 AS n) SELECT n FROM a",
    "trailing semicolon": "SELECT 1;",
    "trailing semicolon and space": "SELECT 1 ;  \n",
    "semicolon in string": "SELECT 'a;b' AS x",
    "keyword in string": "SELECT 'DROP TABLE invoices; PRAGMA x' AS x",
    "escaped quote in string": "SELECT 'it''s; DROP' AS x",
    "keyword in double quotes": 'SELECT "update" FROM t',
    "keyword in brackets": "SELECT [delete] FROM t",
    "keyword in backticks": "SELECT `drop` FROM t",
    "keyword in line comment": "SELECT 1 -- ; DROP TABLE invoices",
    "keyword in block comment": "SELECT /* DELETE; */ 1",
    "leading comment": "/* note */ SELECT 1",
    "similar column names": "SELECT created_at, updated_at, delete_flag FROM t",
    "replace function": "SELECT REPLACE(company_name, 'a', 'b') FROM customers",
}


@pytest.mark.parametrize("sql", UNSAFE.values(), ids=UNSAFE.keys())
def test_unsafe_sql_is_rejected(sql):
    with pytest.raises(UnsafeSQLError):
        validate_sql(sql)


@pytest.mark.parametrize("sql", SAFE.values(), ids=SAFE.keys())
def test_safe_sql_is_accepted(sql):
    assert validate_sql(sql) == sql.strip()


def test_rejection_message_is_safe_to_show():
    with pytest.raises(UnsafeSQLError) as info:
        validate_sql("DROP TABLE invoices")
    assert info.value.user_message == "Only SELECT queries are allowed; AskDB is read-only."


def test_rejection_names_the_forbidden_keyword_inside_a_cte():
    with pytest.raises(UnsafeSQLError) as info:
        validate_sql("WITH x AS (SELECT 1) DELETE FROM invoices")
    assert "DELETE" in info.value.user_message
