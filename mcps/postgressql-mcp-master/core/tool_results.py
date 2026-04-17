from typing import Any, Optional

from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel, ConfigDict, Field


class ToolErrorPayload(BaseModel):
    code: str
    message: str
    database: Optional[str] = None
    retryable: bool = False


class QuerySuccessPayload(BaseModel):
    database: str
    row_count: int
    limit_applied: int
    executed_sql: str
    data: list[dict[str, Any]]


class TableSummaryPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_name: str = Field(alias="schema")
    name: str
    size: str
    row_estimate: Optional[int] = None


class ListTablesSuccessPayload(BaseModel):
    database: str
    schema_filter: Optional[str] = None
    table_count: int
    tables: list[TableSummaryPayload]


class ColumnPayload(BaseModel):
    name: str
    data_type: str
    is_nullable: str
    default: Optional[str] = None
    key: Optional[str] = None


class ForeignKeyPayload(BaseModel):
    column: str
    reference_schema: str
    reference_table: str
    reference_column: str


class IndexPayload(BaseModel):
    name: str
    index_type: str
    columns: list[str]
    is_unique: bool = False
    is_primary: bool = False


class DescribeTableSuccessPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    database: str
    schema_name: str = Field(alias="schema")
    table: str
    columns: list[ColumnPayload]
    foreign_keys: list[ForeignKeyPayload]
    indexes: list[IndexPayload]


def _structured_payload(payload: BaseModel | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, BaseModel):
        return payload.model_dump(mode="json", by_alias=True)
    return payload


def success_result(text: str, payload: BaseModel | dict[str, Any]) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structuredContent=_structured_payload(payload),
        isError=False,
    )


def error_result(text: str, payload: BaseModel | dict[str, Any]) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structuredContent=_structured_payload(payload),
        isError=True,
    )
