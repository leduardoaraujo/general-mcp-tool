from __future__ import annotations

from typing import Any

from mcp_orchestrator.domain.enums import Domain, McpTarget, TaskType
from mcp_orchestrator.domain.models import EnrichedRequest

from .base import BaseMockMcpClient


class PostgreSqlMcpClient(BaseMockMcpClient):
    name = "postgresql"
    target = McpTarget.POSTGRESQL

    def can_handle(self, enriched_request: EnrichedRequest) -> bool:
        return (
            super().can_handle(enriched_request)
            or enriched_request.interpretation.domain == Domain.POSTGRESQL
            or enriched_request.interpretation.task_type == TaskType.SQL_QUERY
        )

    def _summary(self, enriched_request: EnrichedRequest) -> str:
        return "PostgreSQL MCP mock prepared a SQL response."

    def _structured_data(self, enriched_request: EnrichedRequest) -> dict[str, Any]:
        return {
            "database": "analytics",
            "dialect": "postgresql",
            "tables": ["sales_orders", "customers"],
        }
