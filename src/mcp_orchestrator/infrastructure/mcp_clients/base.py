from __future__ import annotations

from time import perf_counter
from typing import Any

from mcp_orchestrator.domain.enums import McpTarget, ResultStatus
from mcp_orchestrator.domain.models import EnrichedRequest, MCPResult


class BaseMockMcpClient:
    name: str
    target: McpTarget

    def can_handle(self, enriched_request: EnrichedRequest) -> bool:
        return self.target in enriched_request.interpretation.candidate_mcps

    async def execute(self, enriched_request: EnrichedRequest) -> MCPResult:
        started_at = perf_counter()
        data = self._structured_data(enriched_request)
        duration_ms = (perf_counter() - started_at) * 1000
        return MCPResult(
            mcp_name=self.name,
            status=ResultStatus.SUCCESS,
            summary=self._summary(enriched_request),
            raw_output={
                "mock": True,
                "target": self.target.value,
                "intent": enriched_request.interpretation.intent,
            },
            structured_data=data,
            sources_used=self._sources(enriched_request),
            trace=[
                f"{self.name} received enriched request {enriched_request.correlation_id}.",
                f"{self.name} used {len(enriched_request.rag_context.items)} context items.",
            ],
            errors=[],
            warnings=self._warnings(enriched_request),
            duration_ms=duration_ms,
        )

    def _summary(self, enriched_request: EnrichedRequest) -> str:
        return f"{self.name} produced a mock response."

    def _structured_data(self, enriched_request: EnrichedRequest) -> dict[str, Any]:
        return {
            "mcp": self.target.value,
            "domain": enriched_request.interpretation.domain.value,
            "task_type": enriched_request.interpretation.task_type.value,
        }

    def _sources(self, enriched_request: EnrichedRequest) -> list[str]:
        return list(dict.fromkeys(item.source_path for item in enriched_request.rag_context.items))

    def _warnings(self, enriched_request: EnrichedRequest) -> list[str]:
        if not enriched_request.rag_context.items:
            return ["No RAG context item was retrieved for this mock execution."]
        return []
