import importlib

import pytest

import core.connection as connection_module


class _AcquireContext:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeConn:
    def __init__(self):
        self.executed = []

    async def execute(self, sql):
        self.executed.append(sql)
        return "SELECT 1"


class FakePool:
    def __init__(self):
        self.conn = FakeConn()
        self.closed = False

    def acquire(self):
        return _AcquireContext(self.conn)

    async def close(self):
        self.closed = True


def reload_connection(monkeypatch, **env):
    keys = [
        "POSTGRES_DSN",
        "POSTGRES_DB_1_NAME",
        "POSTGRES_DB_1_DSN",
        "POSTGRES_DB_2_NAME",
        "POSTGRES_DB_2_DSN",
        "POSTGRES_DB_3_NAME",
        "POSTGRES_DB_3_DSN",
        "POOL_MIN_SIZE",
        "POOL_MAX_SIZE",
        "POOL_COMMAND_TIMEOUT",
        "POOL_CONNECT_TIMEOUT",
        "QUERY_STATEMENT_TIMEOUT_MS",
        "QUERY_LOCK_TIMEOUT_MS",
        "QUERY_IDLE_IN_TRANSACTION_TIMEOUT_MS",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(connection_module)


def test_legacy_configuration_uses_default_alias(monkeypatch):
    module = reload_connection(monkeypatch, POSTGRES_DSN="postgresql://user:pass@localhost:5432/app")

    settings = module.get_settings()

    assert settings.default_database == "default"
    assert [database.alias for database in settings.databases] == ["default"]


def test_multi_database_configuration_uses_first_slot_as_default(monkeypatch):
    module = reload_connection(
        monkeypatch,
        POSTGRES_DB_1_NAME="main",
        POSTGRES_DB_1_DSN="postgresql://user:pass@localhost:5432/app",
        POSTGRES_DB_2_NAME="analytics",
        POSTGRES_DB_2_DSN="postgresql://user:pass@localhost:5432/analytics",
    )

    settings = module.get_settings()

    assert settings.default_database == "main"
    assert [database.alias for database in settings.databases] == ["main", "analytics"]
    assert module.resolve_database_alias(None) == "main"
    assert module.resolve_database_alias("analytics") == "analytics"


def test_multi_database_requires_first_slot(monkeypatch):
    module = reload_connection(
        monkeypatch,
        POSTGRES_DB_2_NAME="analytics",
        POSTGRES_DB_2_DSN="postgresql://user:pass@localhost:5432/analytics",
    )

    with pytest.raises(ValueError, match="POSTGRES_DB_1_NAME and POSTGRES_DB_1_DSN are required"):
        module.get_settings()


def test_duplicate_aliases_are_rejected(monkeypatch):
    module = reload_connection(
        monkeypatch,
        POSTGRES_DB_1_NAME="main",
        POSTGRES_DB_1_DSN="postgresql://user:pass@localhost:5432/app",
        POSTGRES_DB_2_NAME="main",
        POSTGRES_DB_2_DSN="postgresql://user:pass@localhost:5432/analytics",
    )

    with pytest.raises(ValueError, match="Duplicate database alias"):
        module.get_settings()


@pytest.mark.asyncio
async def test_initialize_pools_creates_all_configured_pools(monkeypatch):
    module = reload_connection(
        monkeypatch,
        POSTGRES_DB_1_NAME="main",
        POSTGRES_DB_1_DSN="postgresql://user:pass@localhost:5432/app",
        POSTGRES_DB_2_NAME="analytics",
        POSTGRES_DB_2_DSN="postgresql://user:pass@localhost:5432/analytics",
    )

    created = []

    async def fake_create_pool(**kwargs):
        created.append(kwargs["dsn"])
        return FakePool()

    monkeypatch.setattr(module.asyncpg, "create_pool", fake_create_pool)

    await module.initialize_pools()
    assert created == [
        "postgresql://user:pass@localhost:5432/app",
        "postgresql://user:pass@localhost:5432/analytics",
    ]

    await module.close_pools()
