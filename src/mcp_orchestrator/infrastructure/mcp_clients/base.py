from __future__ import annotations

from time import perf_counter
from typing import Any

from mcp_orchestrator.domain.enums import McpTarget, ResultStatus
from mcp_orchestrator.domain.models import (
    EnrichedRequest,
    ExecutionPlan,
    SpecialistExecutionRequest,
    SpecialistExecutionResult,
)


class PlaceholderMcpClient:
    name: str
    target: McpTarget

    def can_handle(self, plan: ExecutionPlan, request: EnrichedRequest) -> bool:
        return self.target in plan.target_mcps

    async def execute(self, request: SpecialistExecutionRequest) -> SpecialistExecutionResult:
        started_at = perf_counter()
        duration_ms = (perf_counter() - started_at) * 1000
        return SpecialistExecutionResult(
            mcp_name=self.name,
            target=self.target,
            status=ResultStatus.ERROR,
            summary=f"{self.name} is not integrated in Phase 0.",
            structured_data=self._structured_data(request),
            sources_used=self._sources(request),
            trace=[
                f"{self.name} received enriched request {request.correlation_id}.",
                f"{self.name} is registered as a future specialist integration.",
            ],
            errors=[f"{self.name} client is a placeholder."],
            warnings=[],
            duration_ms=duration_ms,
            debug={"phase": "placeholder", "target": self.target.value},
        )

    def _structured_data(self, request: SpecialistExecutionRequest) -> dict[str, Any]:
        return {
            "mcp": self.target.value,
            "domain": request.enriched_request.understanding.domain.value,
            "task_type": request.enriched_request.understanding.task_type.value,
        }

    def _sources(self, request: SpecialistExecutionRequest) -> list[str]:
        return list(
            dict.fromkeys(
                item.source_path
                for item in request.enriched_request.retrieved_context.items
            )
        )


BaseMockMcpClient = PlaceholderMcpClient
