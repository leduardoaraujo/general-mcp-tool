from __future__ import annotations

from typing import Any

from mcp_orchestrator.domain.enums import Domain, McpTarget, TaskType
from mcp_orchestrator.domain.models import EnrichedRequest

from .base import BaseMockMcpClient


class ExcelMcpClient(BaseMockMcpClient):
    name = "excel"
    target = McpTarget.EXCEL

    def can_handle(self, enriched_request: EnrichedRequest) -> bool:
        return (
            super().can_handle(enriched_request)
            or enriched_request.interpretation.domain == Domain.EXCEL
            or enriched_request.interpretation.task_type == TaskType.TABULAR_EXTRACTION
        )

    def _summary(self, enriched_request: EnrichedRequest) -> str:
        return "Excel MCP mock prepared a tabular extraction response."

    def _structured_data(self, enriched_request: EnrichedRequest) -> dict[str, Any]:
        return {
            "workbook": "sales.xlsx",
            "worksheets": ["Orders", "Customers"],
            "operation": "tabular_extraction",
        }
