from __future__ import annotations

from mcp_orchestrator.domain.enums import Domain, McpTarget, TaskType
from mcp_orchestrator.domain.models import EnrichedRequest, ExecutionPlan

from .base import PlaceholderMcpClient


class SqlServerMcpClient(PlaceholderMcpClient):
    name = "sql_server"
    target = McpTarget.SQL_SERVER

    def can_handle(self, plan: ExecutionPlan, request: EnrichedRequest) -> bool:
        return (
            super().can_handle(plan, request)
            or request.understanding.domain == Domain.SQL_SERVER
        )
