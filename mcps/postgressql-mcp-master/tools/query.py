import logging
from enum import Enum
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult
from pydantic import BaseModel, ConfigDict, Field

from core.connection import apply_readonly_session_guards, get_pool, resolve_database_alias
from core.errors import sanitize_error
from core.formatters import format_as_json, format_as_markdown_table, records_to_dict
from core.query_validation import normalize_readonly_query
from core.tool_results import QuerySuccessPayload, ToolErrorPayload, error_result, success_result

logger = logging.getLogger(__name__)


class ResponseFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"


class ExecuteQueryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    sql: str = Field(
        ...,
        description="SQL SELECT to execute. The MCP server validates it as read-only.",
        min_length=1,
        max_length=10_000,
    )
    limit: int = Field(
        default=100,
        description="Maximum number of rows returned",
        ge=1,
        le=5000,
    )
    format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="'markdown' for human-readable output, 'json' for programmatic text output",
    )
    database: Optional[str] = Field(
        default=None,
        description="Optional configured database alias. Uses the default database when omitted.",
    )


def register_query_tools(mcp: FastMCP) -> None:
    @mcp.tool(
        name="pg_execute_query",
        annotations={
            "title": "Execute SQL Query",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def pg_execute_query(params: ExecuteQueryInput) -> CallToolResult:
        """Execute a single validated read-only SQL query against PostgreSQL."""

        database = None
        try:
            database = resolve_database_alias(params.database)
            normalized_query = normalize_readonly_query(params.sql, params.limit)
            pool = await get_pool(database)

            async with pool.acquire() as conn:
                async with conn.transaction():
                    await apply_readonly_session_guards(conn)
                    records = await conn.fetch(normalized_query.sql)
        except Exception as exc:
            tool_error = sanitize_error(exc, database=database)
            logger.warning(
                "pg_execute_query failed code=%s database=%s",
                tool_error.code,
                tool_error.database or database,
            )
            return error_result(
                tool_error.message,
                ToolErrorPayload(
                    code=tool_error.code,
                    message=tool_error.message,
                    database=tool_error.database or database,
                    retryable=tool_error.retryable,
                ),
            )

        data = records_to_dict(records)
        payload = QuerySuccessPayload(
            database=database,
            row_count=len(data),
            limit_applied=normalized_query.limit_applied,
            executed_sql=normalized_query.sql,
            data=data,
        )

        if params.format == ResponseFormat.JSON:
            text = format_as_json(payload.model_dump(mode="json"))
        else:
            table = format_as_markdown_table(data)
            text = (
                f"Database: `{database}`\n"
                f"Rows returned: **{len(data)}**\n"
                f"Limit applied: **{normalized_query.limit_applied}**\n\n"
                f"{table}"
            )

        return success_result(text, payload)
