"""NL2SQL 安全护栏的回归测试（纯本地，不调模型）。

`src/db_tool.py` 会执行模型生成的 SQL，是整个项目风险最高的地方。
它的防线有四道：只允许 SELECT、危险关键字拦截、表名白名单、强制 LIMIT。
这里逐条验证，防止以后重构时被悄悄拆掉。
"""
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.db_tool as db  # noqa: E402


@pytest.fixture()
def sample_db(tmp_path, monkeypatch):
    path = tmp_path / "demo.db"
    con = sqlite3.connect(str(path))
    con.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL);
        INSERT INTO users (name, age) VALUES ('张三', 20), ('李四', 30);
        INSERT INTO orders (user_id, amount) VALUES (1, 99.5), (2, 20.0);
        """
    )
    con.commit()
    con.close()
    monkeypatch.setattr(db, "DB_PATH", str(path))
    return str(path)


def test_allows_simple_select(sample_db):
    sql = db._validate("SELECT name FROM users", 50)
    assert sql.lower().startswith("select")
    assert "limit 50" in sql.lower()


def test_appends_limit_when_missing(sample_db):
    sql = db._validate("SELECT * FROM users WHERE age > 10", 10)
    assert sql.lower().endswith("limit 10")


def test_keeps_existing_limit(sample_db):
    sql = db._validate("SELECT * FROM users LIMIT 3", 50)
    assert sql.lower().count("limit") == 1


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM users",
        "UPDATE users SET age = 1",
        "DROP TABLE users",
        "INSERT INTO users (name) VALUES ('x')",
        "ALTER TABLE users ADD COLUMN x INT",
        "PRAGMA table_info(users)",
    ],
)
def test_rejects_write_and_pragma(sample_db, sql):
    with pytest.raises(ValueError):
        db._validate(sql, 50)


def test_rejects_unknown_table(sample_db):
    """模型臆造表名最常见，必须拦下来而不是让它返回空结果。"""
    with pytest.raises(ValueError) as exc:
        db._validate("SELECT * FROM 库存表", 50)
    assert "不存在" in str(exc.value)


def test_rejects_schema_qualified_table(sample_db):
    """FROM main.users 这种绕过白名单的写法也要挡。"""
    with pytest.raises(ValueError):
        db._validate("SELECT * FROM main.users", 50)


def test_allows_with_cte(sample_db):
    sql = db._validate(
        "WITH t AS (SELECT id FROM users) SELECT * FROM t", 50
    )
    assert sql.lower().startswith("with")


def test_rejects_joint_delete_in_cte(sample_db):
    with pytest.raises(ValueError):
        db._validate("WITH t AS (DELETE FROM users) SELECT 1", 50)


def test_rejects_multi_statement_with_drop(sample_db):
    with pytest.raises(ValueError):
        db._validate("SELECT 1; DROP TABLE users", 50)


def test_schema_only_lists_real_tables(sample_db):
    schema = db.get_schema(sample_db)
    assert "users" in schema and "orders" in schema
    assert "sqlite_sequence" not in schema


def test_get_tables_returns_lowercase(sample_db):
    assert db.get_tables(sample_db) == {"users", "orders"}
