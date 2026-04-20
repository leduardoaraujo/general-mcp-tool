from __future__ import annotations

from mcp_orchestrator.domain.enums import Domain, McpTarget, TaskType
from mcp_orchestrator.domain.models import EnrichedRequest, ExecutionPlan

from .base import PlaceholderMcpClient


class PowerBiMcpClient(PlaceholderMcpClient):
    name = "power_bi"
    target = McpTarget.POWER_BI

    def can_handle(self, plan: ExecutionPlan, request: EnrichedRequest) -> bool:
        return (
            super().can_handle(plan, request)
            or request.understanding.domain == Domain.POWER_BI
            or request.understanding.task_type == TaskType.SEMANTIC_MODEL_QUERY
        )
