from types import SimpleNamespace

import pytest

from tools import query as query_tools
from tools import schema as schema_tools


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self, name, annotations=None):
        def decorator(func):
            self.tools[name] = func
            return func

        return decorator


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeConn:
    def __init__(self, fetch_results=None, fetch_side_effect=None):
        self.fetch_results = list(fetch_results or [])
        self.fetch_side_effect = fetch_side_effect
        self.fetch_calls = []
        self.fetchval_calls = []
        self.execute_calls = []

    def transaction(self):
        return FakeTransaction()

    async def execute(self, sql):
        self.execute_calls.append(sql)
        return "OK"

    async def fetchval(self, sql, value):
        self.fetchval_calls.append((sql, value))
        return value

    async def fetch(self, sql, *args):
        self.fetch_calls.append((sql, args))
        if self.fetch_side_effect is not None:
            raise self.fetch_side_effect
        if self.fetch_results:
            return self.fetch_results.pop(0)
        return []


class FakeAcquireContext:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return FakeAcquireContext(self.conn)


class UndefinedTableError(Exception):
    pass


@pytest.mark.asyncio
async def test_pg_execute_query_returns_structured_success(monkeypatch):
    mcp = FakeMCP()
    query_tools.register_query_tools(mcp)
    tool = mcp.tools["pg_execute_query"]

    conn = FakeConn(fetch_results=[[{"id": 1, "name": "Alice"}]])
    monkeypatch.setattr(query_tools, "resolve_database_alias", lambda alias: "main")
    
    async def fake_get_pool(alias):
        return FakePool(conn)

    monkeypatch.setattr(query_tools, "get_pool", fake_get_pool)
    monkeypatch.setattr(
        query_tools,
        "normalize_readonly_query",
        lambda sql, limit: SimpleNamespace(sql="SELECT * FROM users LIMIT 10", limit_applied=10),
    )

    async def fake_guards(connection):
        await connection.fetchval("SELECT set_config('statement_timeout', $1, true)", "10000ms")

    monkeypatch.setattr(query_tools, "apply_readonly_session_guards", fake_guards)

    result = await tool(
        query_tools.ExecuteQueryInput(sql="SELECT * FROM users", limit=10, format="markdown")
    )

    assert result.isError is False
    assert result.structuredContent["database"] == "main"
    assert result.structuredContent["row_count"] == 1
    assert "Database: `main`" in result.content[0].text


@pytest.mark.asyncio
async def test_pg_execute_query_sanitizes_database_errors(monkeypatch):
    mcp = FakeMCP()
    query_tools.register_query_tools(mcp)
    tool = mcp.tools["pg_execute_query"]

    conn = FakeConn(fetch_side_effect=UndefinedTableError("users does not exist"))
    monkeypatch.setattr(query_tools, "resolve_database_alias", lambda alias: "main")

    async def fake_get_pool(alias):
        return FakePool(conn)

    monkeypatch.setattr(query_tools, "get_pool", fake_get_pool)
    monkeypatch.setattr(
        query_tools,
        "normalize_readonly_query",
        lambda sql, limit: SimpleNamespace(sql="SELECT * FROM users LIMIT 10", limit_applied=10),
    )

    async def fake_guards(connection):
        await connection.fetchval("SELECT set_config('statement_timeout', $1, true)", "10000ms")

    monkeypatch.setattr(query_tools, "apply_readonly_session_guards", fake_guards)

    result = await tool(query_tools.ExecuteQueryInput(sql="SELECT * FROM users", limit=10))

    assert result.isError is True
    assert result.structuredContent["code"] == "not_found"


@pytest.mark.asyncio
async def test_pg_list_tables_applies_readonly_guards(monkeypatch):
    mcp = FakeMCP()
    schema_tools.register_schema_tools(mcp)
    tool = mcp.tools["pg_list_tables"]

    conn = FakeConn(
        fetch_results=[
            [
                {
                    "table_schema": "public",
                    "table_name": "users",
                    "size": "16 kB",
                    "row_estimate": 12,
                }
            ]
        ]
    )
    monkeypatch.setattr(schema_tools, "resolve_database_alias", lambda alias: "main")

    async def fake_get_pool(alias):
        return FakePool(conn)

    monkeypatch.setattr(schema_tools, "get_pool", fake_get_pool)

    async def fake_guards(connection):
        await connection.fetchval("SELECT set_config('lock_timeout', $1, true)", "1000ms")

    monkeypatch.setattr(schema_tools, "apply_readonly_session_guards", fake_guards)

    result = await tool(schema_tools.ListTablesInput(schema_name="public", database="main"))

    assert result.isError is False
    assert result.structuredContent["table_count"] == 1
    assert conn.fetchval_calls


@pytest.mark.asyncio
async def test_pg_describe_table_returns_not_found_when_table_is_missing(monkeypatch):
    mcp = FakeMCP()
    schema_tools.register_schema_tools(mcp)
    tool = mcp.tools["pg_describe_table"]

    conn = FakeConn(fetch_results=[[], [], []])
    monkeypatch.setattr(schema_tools, "resolve_database_alias", lambda alias: "main")

    async def fake_get_pool(alias):
        return FakePool(conn)

    monkeypatch.setattr(schema_tools, "get_pool", fake_get_pool)

    async def fake_guards(connection):
        await connection.fetchval("SELECT set_config('idle_in_transaction_session_timeout', $1, true)", "15000ms")

    monkeypatch.setattr(schema_tools, "apply_readonly_session_guards", fake_guards)

    result = await tool(
        schema_tools.DescribeTableInput(table_name="missing_table", schema_name="public")
    )

    assert result.isError is True
    assert result.structuredContent["code"] == "not_found"
