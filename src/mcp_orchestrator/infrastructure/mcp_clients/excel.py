from __future__ import annotations

from mcp_orchestrator.domain.enums import Domain, McpTarget, TaskType
from mcp_orchestrator.domain.models import EnrichedRequest, ExecutionPlan

from .base import PlaceholderMcpClient


class ExcelMcpClient(PlaceholderMcpClient):
    name = "excel"
    target = McpTarget.EXCEL

    def can_handle(self, plan: ExecutionPlan, request: EnrichedRequest) -> bool:
        return (
            super().can_handle(plan, request)
            or request.understanding.domain == Domain.EXCEL
            or request.understanding.task_type == TaskType.TABULAR_EXTRACTION
        )
