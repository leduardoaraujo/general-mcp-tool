import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult
from pydantic import BaseModel, ConfigDict, Field

from core.connection import apply_readonly_session_guards, get_pool, resolve_database_alias
from core.errors import MCPToolError, sanitize_error
from core.formatters import format_as_markdown_table
from core.tool_results import (
    ColumnPayload,
    DescribeTableSuccessPayload,
    ForeignKeyPayload,
    IndexPayload,
    ListTablesSuccessPayload,
    TableSummaryPayload,
    ToolErrorPayload,
    error_result,
    success_result,
)

logger = logging.getLogger(__name__)


class ListTablesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    schema_name: Optional[str] = Field(
        default=None,
        description="Filter by PostgreSQL schema (e.g. 'public'). If omitted, lists all user schemas.",
    )
    database: Optional[str] = Field(
        default=None,
        description="Optional configured database alias. Uses the default database when omitted.",
    )


class DescribeTableInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    table_name: str = Field(..., description="Table name", min_length=1)
    schema_name: str = Field(default="public", description="PostgreSQL schema")
    database: Optional[str] = Field(
        default=None,
        description="Optional configured database alias. Uses the default database when omitted.",
    )


def _format_list_tables_markdown(
    database: str,
    tables: list[TableSummaryPayload],
    schema_filter: Optional[str],
) -> str:
    header = f"## Available tables (`{database}`)\n"
    if schema_filter:
        header += f"Schema filter: `{schema_filter}`\n"

    if not tables:
        return header + "\nNo tables found."

    lines = [header]
    for table in tables:
        estimate = table.row_estimate if table.row_estimate is not None else "unknown"
        lines.append(f"- **{table.schema}.{table.name}** - {table.size} (~{estimate} rows)")
    return "\n".join(lines)


def _format_describe_table_markdown(payload: DescribeTableSuccessPayload) -> str:
    lines = [
        f"## Structure: `{payload.database}:{payload.schema_name}.{payload.table}`\n",
        format_as_markdown_table(
            [
                {
                    "Column": column.name,
                    "Type": column.data_type,
                    "Nullable": column.is_nullable,
                    "Default": column.default,
                    "Key": column.key,
                }
                for column in payload.columns
            ]
        ),
    ]

    if payload.foreign_keys:
        lines.append("\n### Foreign Keys\n")
        for foreign_key in payload.foreign_keys:
            lines.append(
                f"- `{foreign_key.column}` -> "
                f"`{foreign_key.reference_schema}.{foreign_key.reference_table}.{foreign_key.reference_column}`"
            )

    if payload.indexes:
        lines.append("\n### Indexes\n")
        for index in payload.indexes:
            flags: list[str] = []
            if index.is_primary:
                flags.append("PRIMARY")
            elif index.is_unique:
                flags.append("UNIQUE")
            flag_text = f" ({', '.join(flags)})" if flags else ""
            lines.append(
                f"- **{index.name}** [{index.index_type}] on ({', '.join(index.columns)}){flag_text}"
            )

    return "\n".join(lines)


def register_schema_tools(mcp: FastMCP) -> None:
    @mcp.tool(
        name="pg_list_tables",
        annotations={"title": "List Tables", "readOnlyHint": True, "destructiveHint": False},
    )
    async def pg_list_tables(params: ListTablesInput) -> CallToolResult:
        """List available tables in the selected database."""

        sql = """
            SELECT
                table_schema,
                table_name,
                pg_size_pretty(pg_total_relation_size(quote_ident(table_schema) || '.' || quote_ident(table_name))) AS size,
                (
                    SELECT reltuples::bigint
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relname = t.table_name
                      AND n.nspname = t.table_schema
                ) AS row_estimate
            FROM information_schema.tables t
            WHERE table_type = 'BASE TABLE'
              AND table_schema NOT IN ('pg_catalog', 'information_schema')
              AND ($1::text IS NULL OR table_schema = $1)
            ORDER BY table_schema, table_name;
        """

        database = None
        try:
            database = resolve_database_alias(params.database)
            pool = await get_pool(database)
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await apply_readonly_session_guards(conn)
                    records = await conn.fetch(sql, params.schema_name)
        except Exception as exc:
            tool_error = sanitize_error(exc, database=database)
            logger.warning(
                "pg_list_tables failed code=%s database=%s",
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

        tables = [
            TableSummaryPayload(
                schema_name=record["table_schema"],
                name=record["table_name"],
                size=record["size"],
                row_estimate=record["row_estimate"],
            )
            for record in records
        ]
        payload = ListTablesSuccessPayload(
            database=database,
            schema_filter=params.schema_name,
            table_count=len(tables),
            tables=tables,
        )
        return success_result(
            _format_list_tables_markdown(database, tables, params.schema_name),
            payload,
        )

    @mcp.tool(
        name="pg_describe_table",
        annotations={"title": "Describe Table", "readOnlyHint": True, "destructiveHint": False},
    )
    async def pg_describe_table(params: DescribeTableInput) -> CallToolResult:
        """Return the structure of a table: columns, foreign keys, and indexes."""

        columns_sql = """
            SELECT
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.column_default,
                CASE WHEN pk.column_name IS NOT NULL THEN 'PK' ELSE '' END AS key
            FROM information_schema.columns c
            LEFT JOIN (
                SELECT ku.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage ku
                  ON tc.constraint_name = ku.constraint_name
                 AND tc.constraint_schema = ku.constraint_schema
                 AND tc.table_schema = ku.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
                  AND tc.table_name = $1
                  AND tc.table_schema = $2
            ) pk ON c.column_name = pk.column_name
            WHERE c.table_name = $1 AND c.table_schema = $2
            ORDER BY c.ordinal_position;
        """

        fk_sql = """
            SELECT
                ku.column_name,
                ccu.table_schema AS ref_schema,
                ccu.table_name AS ref_table,
                ccu.column_name AS ref_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage ku
              ON tc.constraint_name = ku.constraint_name
             AND tc.constraint_schema = ku.constraint_schema
             AND tc.table_schema = ku.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON tc.constraint_name = ccu.constraint_name
             AND tc.constraint_schema = ccu.constraint_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_name = $1
              AND tc.table_schema = $2
            ORDER BY ku.column_name;
        """

        indexes_sql = """
            SELECT
                i.relname AS index_name,
                am.amname AS index_type,
                array_agg(a.attname ORDER BY x.ordinality) AS columns,
                ix.indisunique AS is_unique,
                ix.indisprimary AS is_primary
            FROM pg_index ix
            JOIN pg_class t ON t.oid = ix.indrelid
            JOIN pg_class i ON i.oid = ix.indexrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN pg_am am ON am.oid = i.relam
            JOIN LATERAL unnest(ix.indkey) WITH ORDINALITY AS x(attnum, ordinality) ON TRUE
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = x.attnum
            WHERE t.relname = $1 AND n.nspname = $2
            GROUP BY i.relname, am.amname, ix.indisunique, ix.indisprimary
            ORDER BY i.relname;
        """

        database = None
        try:
            database = resolve_database_alias(params.database)
            pool = await get_pool(database)
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await apply_readonly_session_guards(conn)
                    columns = await conn.fetch(columns_sql, params.table_name, params.schema_name)
                    foreign_keys = await conn.fetch(fk_sql, params.table_name, params.schema_name)
                    indexes = await conn.fetch(indexes_sql, params.table_name, params.schema_name)
        except Exception as exc:
            tool_error = sanitize_error(exc, database=database)
            logger.warning(
                "pg_describe_table failed code=%s database=%s",
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

        if not columns:
            tool_error = MCPToolError(
                code="not_found",
                message=f"Table `{params.schema_name}.{params.table_name}` was not found.",
                retryable=False,
                database=database,
            )
            return error_result(
                tool_error.message,
                ToolErrorPayload(
                    code=tool_error.code,
                    message=tool_error.message,
                    database=tool_error.database,
                    retryable=tool_error.retryable,
                ),
            )

        payload = DescribeTableSuccessPayload(
            database=database,
            schema_name=params.schema_name,
            table=params.table_name,
            columns=[
                ColumnPayload(
                    name=record["column_name"],
                    data_type=record["data_type"],
                    is_nullable=record["is_nullable"],
                    default=record["column_default"],
                    key=record["key"] or None,
                )
                for record in columns
            ],
            foreign_keys=[
                ForeignKeyPayload(
                    column=record["column_name"],
                    reference_schema=record["ref_schema"],
                    reference_table=record["ref_table"],
                    reference_column=record["ref_column"],
                )
                for record in foreign_keys
            ],
            indexes=[
                IndexPayload(
                    name=record["index_name"],
                    index_type=record["index_type"],
                    columns=list(record["columns"]),
                    is_unique=record["is_unique"],
                    is_primary=record["is_primary"],
                )
                for record in indexes
            ],
        )
        return success_result(_format_describe_table_markdown(payload), payload)
