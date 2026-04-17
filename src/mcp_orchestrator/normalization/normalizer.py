from __future__ import annotations

from typing import Any

from mcp_orchestrator.domain.enums import ResultStatus
from mcp_orchestrator.domain.models import MCPResult, NormalizedResponse


class DefaultResponseNormalizer:
    def normalize(
        self,
        correlation_id: str,
        results: list[MCPResult],
        timings: dict[str, float],
    ) -> NormalizedResponse:
        status = self._status(results)
        errors = [error for result in results for error in result.errors]
        warnings = [warning for result in results for warning in result.warnings]
        sources = list(dict.fromkeys(source for result in results for source in result.sources_used))
        trace = [trace_item for result in results for trace_item in result.trace]

        return NormalizedResponse(
            correlation_id=correlation_id,
            status=status,
            summary=self._summary(results, status),
            raw_outputs=results,
            structured_data=self._structured_data(results),
            sources_used=sources,
            mcp_trace=trace,
            errors=errors,
            warnings=warnings,
            next_actions=self._next_actions(status, errors),
            timings={key: round(value, 3) for key, value in timings.items()},
        )

    def _status(self, results: list[MCPResult]) -> ResultStatus:
        if not results:
            return ResultStatus.ERROR
        success_count = sum(1 for result in results if result.status == ResultStatus.SUCCESS)
        if success_count == len(results):
            return ResultStatus.SUCCESS
        if success_count:
            return ResultStatus.PARTIAL_SUCCESS
        return ResultStatus.ERROR

    def _summary(self, results: list[MCPResult], status: ResultStatus) -> str:
        if not results:
            return "No MCP results were produced."
        if status == ResultStatus.SUCCESS:
            return "MCP Orchestrator completed the request successfully."
        if status == ResultStatus.PARTIAL_SUCCESS:
            return "MCP Orchestrator completed the request with partial success."
        return "MCP Orchestrator could not complete the request."

    def _structured_data(self, results: list[MCPResult]) -> dict[str, Any]:
        return {
            result.mcp_name: result.structured_data
            for result in results
            if result.structured_data is not None
        }

    def _next_actions(self, status: ResultStatus, errors: list[str]) -> list[str]:
        if status == ResultStatus.SUCCESS:
            return ["Review structured_data and sources_used."]
        return [
            "Review errors and mcp_trace.",
            "Adjust the request or add more context documents.",
            *errors[:1],
        ]
