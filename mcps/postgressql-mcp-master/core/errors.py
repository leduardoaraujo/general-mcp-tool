import logging
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)


class MCPToolError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        retryable: bool = False,
        database: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.database = database


def sanitize_error(exc: Exception, database: Optional[str] = None) -> MCPToolError:
    if isinstance(exc, MCPToolError):
        if database is not None and exc.database is None:
            return MCPToolError(
                code=exc.code,
                message=exc.message,
                retryable=exc.retryable,
                database=database,
            )
        return exc

    error_name = exc.__class__.__name__

    if isinstance(exc, ValueError):
        return MCPToolError(
            code="invalid_request",
            message=str(exc),
            retryable=False,
            database=database,
        )

    if error_name in {"UndefinedTableError", "UndefinedObjectError"}:
        return MCPToolError(
            code="not_found",
            message="The requested table or relation was not found.",
            retryable=False,
            database=database,
        )

    if error_name in {"PostgresSyntaxError", "SyntaxOrAccessError"}:
        return MCPToolError(
            code="invalid_query",
            message="The SQL query is invalid for this PostgreSQL server.",
            retryable=False,
            database=database,
        )

    if error_name in {"QueryCanceledError"}:
        return MCPToolError(
            code="query_timeout",
            message="The query exceeded the configured statement timeout.",
            retryable=True,
            database=database,
        )

    if error_name in {"LockNotAvailableError", "DeadlockDetectedError"}:
        return MCPToolError(
            code="lock_timeout",
            message="The query could not acquire the required lock within the timeout.",
            retryable=True,
            database=database,
        )

    if error_name in {"InsufficientPrivilegeError"}:
        return MCPToolError(
            code="permission_denied",
            message="The configured database role does not have permission for this operation.",
            retryable=False,
            database=database,
        )

    if error_name in {"InvalidCatalogNameError"}:
        return MCPToolError(
            code="connection_error",
            message="The configured database does not exist or is not reachable.",
            retryable=False,
            database=database,
        )

    connection_error_types = [asyncpg.InterfaceError]
    postgres_connection_error = getattr(asyncpg, "PostgresConnectionError", None)
    if postgres_connection_error is not None:
        connection_error_types.append(postgres_connection_error)

    if isinstance(exc, tuple(connection_error_types)):
        return MCPToolError(
            code="connection_error",
            message="The MCP server could not connect to the configured PostgreSQL database.",
            retryable=True,
            database=database,
        )

    if isinstance(exc, asyncpg.PostgresError):
        return MCPToolError(
            code="database_error",
            message="PostgreSQL rejected the request.",
            retryable=False,
            database=database,
        )

    logger.exception("Unhandled tool error type=%s", error_name)
    return MCPToolError(
        code="internal_error",
        message="The MCP server failed to process the request.",
        retryable=False,
        database=database,
    )
