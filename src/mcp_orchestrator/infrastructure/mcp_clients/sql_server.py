from __future__ import annotations

from typing import Any

from mcp_orchestrator.domain.enums import Domain, McpTarget, TaskType
from mcp_orchestrator.domain.models import EnrichedRequest

from .base import BaseMockMcpClient


class SqlServerMcpClient(BaseMockMcpClient):
    name = "sql_server"
    target = McpTarget.SQL_SERVER

    def can_handle(self, enriched_request: EnrichedRequest) -> bool:
        return (
            super().can_handle(enriched_request)
            or enriched_request.interpretation.domain == Domain.SQL_SERVER
            or enriched_request.interpretation.task_type == TaskType.SQL_QUERY
        )

    def _summary(self, enriched_request: EnrichedRequest) -> str:
        return "SQL Server MCP mock prepared a T-SQL response."

    def _structured_data(self, enriched_request: EnrichedRequest) -> dict[str, Any]:
        return {
            "database": "warehouse",
            "dialect": "sql_server",
            "tables": ["fact_sales", "dim_customer"],
        }
