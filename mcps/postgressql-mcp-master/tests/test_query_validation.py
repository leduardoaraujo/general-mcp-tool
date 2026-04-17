import pytest

from core.errors import MCPToolError
from core.query_validation import normalize_readonly_query


def test_select_query_is_normalized_with_limit():
    result = normalize_readonly_query("SELECT * FROM users;", 25)

    assert result.limit_applied == 25
    assert "LIMIT 25" in result.sql.upper()


def test_with_select_query_is_allowed():
    result = normalize_readonly_query(
        "WITH recent AS (SELECT * FROM users) SELECT * FROM recent",
        10,
    )

    assert result.limit_applied == 10
    assert "WITH" in result.sql.upper()


def test_existing_smaller_limit_is_preserved():
    result = normalize_readonly_query("SELECT * FROM users LIMIT 5", 50)

    assert result.limit_applied == 5


def test_multiple_statements_are_rejected():
    with pytest.raises(MCPToolError, match="Only a single SQL statement is allowed"):
        normalize_readonly_query("SELECT 1; SELECT 2;", 10)


def test_write_statements_are_rejected():
    with pytest.raises(MCPToolError, match="Only read-only SELECT queries are supported"):
        normalize_readonly_query("INSERT INTO users(id) VALUES (1)", 10)


def test_locking_clauses_are_rejected():
    with pytest.raises(MCPToolError, match="Row-locking clauses are not allowed"):
        normalize_readonly_query("SELECT * FROM users FOR UPDATE", 10)


def test_advisory_lock_functions_are_rejected():
    with pytest.raises(MCPToolError, match="Locking helper functions are not allowed"):
        normalize_readonly_query("SELECT pg_advisory_lock(1)", 10)
