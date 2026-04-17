import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import asyncpg

from core.errors import MCPToolError

logger = logging.getLogger(__name__)

MAX_DATABASES = 3
DEFAULT_DATABASE_ALIAS = "default"
DEFAULT_POOL_MIN_SIZE = 1
DEFAULT_POOL_MAX_SIZE = 3
DEFAULT_POOL_COMMAND_TIMEOUT = 30
DEFAULT_POOL_CONNECT_TIMEOUT = 10
DEFAULT_STATEMENT_TIMEOUT_MS = 10_000
DEFAULT_LOCK_TIMEOUT_MS = 1_000
DEFAULT_IDLE_IN_TRANSACTION_TIMEOUT_MS = 15_000
STARTUP_CONNECT_RETRIES = 2
STARTUP_CONNECT_RETRY_DELAY_SECONDS = 0.5


@dataclass(frozen=True)
class DatabaseConfig:
    alias: str
    dsn: str


@dataclass(frozen=True)
class ConnectionSettings:
    databases: tuple[DatabaseConfig, ...]
    default_database: str
    pool_min_size: int
    pool_max_size: int
    pool_command_timeout: int
    pool_connect_timeout: int
    statement_timeout_ms: int
    lock_timeout_ms: int
    idle_in_transaction_timeout_ms: int


_settings: Optional[ConnectionSettings] = None
_pools: dict[str, asyncpg.Pool] = {}


def _read_int_env(name: str, default: int, minimum: int = 1) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc

    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}.")

    return value


def _normalize_alias(alias: str) -> str:
    normalized = alias.strip()
    if not normalized:
        raise ValueError("Database alias cannot be empty.")
    return normalized


def _dsn_target(dsn: str) -> str:
    parsed = urlparse(dsn)
    host = parsed.hostname or "unknown-host"
    database = parsed.path.lstrip("/") or "unknown-db"
    if parsed.port:
        return f"{host}:{parsed.port}/{database}"
    return f"{host}/{database}"


def _load_database_configs() -> tuple[tuple[DatabaseConfig, ...], str]:
    slot_mode = any(os.getenv(f"POSTGRES_DB_{index}_DSN") for index in range(1, MAX_DATABASES + 1))

    if slot_mode:
        if not os.getenv("POSTGRES_DB_1_DSN") or not os.getenv("POSTGRES_DB_1_NAME"):
            raise ValueError(
                "POSTGRES_DB_1_NAME and POSTGRES_DB_1_DSN are required when multi-database mode is enabled."
            )

        if os.getenv("POSTGRES_DSN"):
            logger.warning(
                "Ignoring legacy POSTGRES_DSN because multi-database slot configuration is enabled."
            )

        configs: list[DatabaseConfig] = []
        seen_aliases: set[str] = set()

        for index in range(1, MAX_DATABASES + 1):
            alias = os.getenv(f"POSTGRES_DB_{index}_NAME")
            dsn = os.getenv(f"POSTGRES_DB_{index}_DSN")

            if not alias and not dsn:
                continue

            if not alias or not dsn:
                raise ValueError(
                    f"POSTGRES_DB_{index}_NAME and POSTGRES_DB_{index}_DSN must be set together."
                )

            normalized_alias = _normalize_alias(alias)
            if normalized_alias in seen_aliases:
                raise ValueError(f"Duplicate database alias configured: {normalized_alias}")

            seen_aliases.add(normalized_alias)
            configs.append(DatabaseConfig(alias=normalized_alias, dsn=dsn.strip()))

        if not configs:
            raise ValueError(
                "Multi-database mode is enabled, but no valid POSTGRES_DB_{1..3}_NAME/DSN pairs were found."
            )

        return tuple(configs), configs[0].alias

    legacy_dsn = os.getenv("POSTGRES_DSN")
    if not legacy_dsn:
        raise ValueError(
            "Database configuration is missing. Set POSTGRES_DSN for legacy mode or "
            "POSTGRES_DB_{1..3}_NAME/POSTGRES_DB_{1..3}_DSN for multi-database mode."
        )

    return (DatabaseConfig(alias=DEFAULT_DATABASE_ALIAS, dsn=legacy_dsn.strip()),), DEFAULT_DATABASE_ALIAS


def get_settings() -> ConnectionSettings:
    global _settings

    if _settings is None:
        databases, default_database = _load_database_configs()
        pool_min_size = _read_int_env("POOL_MIN_SIZE", DEFAULT_POOL_MIN_SIZE)
        pool_max_size = _read_int_env("POOL_MAX_SIZE", DEFAULT_POOL_MAX_SIZE)
        if pool_max_size < pool_min_size:
            raise ValueError("POOL_MAX_SIZE must be greater than or equal to POOL_MIN_SIZE.")

        _settings = ConnectionSettings(
            databases=databases,
            default_database=default_database,
            pool_min_size=pool_min_size,
            pool_max_size=pool_max_size,
            pool_command_timeout=_read_int_env(
                "POOL_COMMAND_TIMEOUT", DEFAULT_POOL_COMMAND_TIMEOUT
            ),
            pool_connect_timeout=_read_int_env(
                "POOL_CONNECT_TIMEOUT", DEFAULT_POOL_CONNECT_TIMEOUT
            ),
            statement_timeout_ms=_read_int_env(
                "QUERY_STATEMENT_TIMEOUT_MS", DEFAULT_STATEMENT_TIMEOUT_MS
            ),
            lock_timeout_ms=_read_int_env("QUERY_LOCK_TIMEOUT_MS", DEFAULT_LOCK_TIMEOUT_MS),
            idle_in_transaction_timeout_ms=_read_int_env(
                "QUERY_IDLE_IN_TRANSACTION_TIMEOUT_MS",
                DEFAULT_IDLE_IN_TRANSACTION_TIMEOUT_MS,
            ),
        )

    return _settings


def resolve_database_alias(alias: Optional[str] = None) -> str:
    settings = get_settings()
    if alias is None:
        return settings.default_database

    normalized_alias = _normalize_alias(alias)
    known_aliases = {config.alias for config in settings.databases}
    if normalized_alias not in known_aliases:
        raise MCPToolError(
            code="unknown_database",
            message=f"Unknown database alias: {normalized_alias}",
            retryable=False,
            database=normalized_alias,
        )

    return normalized_alias


async def _health_check_pool(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute("SELECT 1")


async def _create_pool(database: DatabaseConfig) -> asyncpg.Pool:
    settings = get_settings()
    logger.info(
        "Connecting to PostgreSQL alias=%s target=%s",
        database.alias,
        _dsn_target(database.dsn),
    )
    pool = await asyncpg.create_pool(
        dsn=database.dsn,
        min_size=settings.pool_min_size,
        max_size=settings.pool_max_size,
        command_timeout=settings.pool_command_timeout,
        timeout=settings.pool_connect_timeout,
    )
    await _health_check_pool(pool)
    logger.info("Connection pool ready for alias=%s", database.alias)
    return pool


async def _create_pool_with_retry(database: DatabaseConfig) -> asyncpg.Pool:
    last_error: Exception | None = None

    for attempt in range(1, STARTUP_CONNECT_RETRIES + 1):
        try:
            return await _create_pool(database)
        except Exception as exc:  # pragma: no cover - exercised through integration paths
            last_error = exc
            logger.warning(
                "Connection pool initialization failed for alias=%s on attempt %s/%s",
                database.alias,
                attempt,
                STARTUP_CONNECT_RETRIES,
            )
            if attempt < STARTUP_CONNECT_RETRIES:
                await asyncio.sleep(STARTUP_CONNECT_RETRY_DELAY_SECONDS)

    assert last_error is not None
    raise last_error


async def initialize_pools() -> None:
    settings = get_settings()
    for database in settings.databases:
        if database.alias not in _pools:
            _pools[database.alias] = await _create_pool_with_retry(database)


async def get_pool(database: Optional[str] = None) -> asyncpg.Pool:
    alias = resolve_database_alias(database)
    if alias in _pools:
        return _pools[alias]

    config = next(item for item in get_settings().databases if item.alias == alias)
    _pools[alias] = await _create_pool(config)
    return _pools[alias]


async def close_pools() -> None:
    aliases = list(_pools.keys())
    for alias in aliases:
        pool = _pools.pop(alias, None)
        if pool is not None:
            await pool.close()
            logger.info("Connection pool closed for alias=%s", alias)


async def apply_readonly_session_guards(conn: asyncpg.Connection) -> None:
    settings = get_settings()
    await conn.execute("SET TRANSACTION READ ONLY")
    await conn.fetchval(
        "SELECT set_config('statement_timeout', $1, true)",
        f"{settings.statement_timeout_ms}ms",
    )
    await conn.fetchval(
        "SELECT set_config('lock_timeout', $1, true)",
        f"{settings.lock_timeout_ms}ms",
    )
    await conn.fetchval(
        "SELECT set_config('idle_in_transaction_session_timeout', $1, true)",
        f"{settings.idle_in_transaction_timeout_ms}ms",
    )
