from __future__ import annotations

from typing import Any

from mcp_orchestrator.domain.enums import Domain, McpTarget, TaskType
from mcp_orchestrator.domain.models import EnrichedRequest

from .base import BaseMockMcpClient


class PowerBiMcpClient(BaseMockMcpClient):
    name = "power_bi"
    target = McpTarget.POWER_BI

    def can_handle(self, enriched_request: EnrichedRequest) -> bool:
        return (
            super().can_handle(enriched_request)
            or enriched_request.interpretation.domain == Domain.POWER_BI
            or enriched_request.interpretation.task_type == TaskType.SEMANTIC_MODEL_QUERY
        )

    def _summary(self, enriched_request: EnrichedRequest) -> str:
        return "Power BI MCP mock prepared a semantic model response."

    def _structured_data(self, enriched_request: EnrichedRequest) -> dict[str, Any]:
        return {
            "semantic_model": "sales_model",
            "measures": ["Total Sales", "Gross Margin"],
            "suggested_query_type": "dax",
        }
