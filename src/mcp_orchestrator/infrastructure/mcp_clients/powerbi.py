from __future__ import annotations

from time import perf_counter
from typing import Any, Protocol

from mcp_orchestrator.domain.enums import Domain, McpTarget, ResultStatus, TaskType
from mcp_orchestrator.domain.models import (
    EnrichedRequest,
    ExecutionPlan,
    McpClientCapability,
    McpToolCallResponse,
    SpecialistExecutionRequest,
    SpecialistExecutionResult,
)
from mcp_orchestrator.infrastructure.mcp_servers import LocalMcpServerCatalog, McpServerDefinition


class ToolRunner(Protocol):
    async def call_tool(
        self,
        server: McpServerDefinition,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> McpToolCallResponse:
        ...


class PowerBiMcpClient:
    name = "power_bi"
    target = McpTarget.POWER_BI

    def __init__(
        self,
        *,
        server_catalog: LocalMcpServerCatalog,
        tool_runner: ToolRunner,
    ) -> None:
        self.server_catalog = server_catalog
        self.tool_runner = tool_runner

    def can_handle(self, plan: ExecutionPlan, request: EnrichedRequest) -> bool:
        return (
            self.target in plan.target_mcps
            or request.understanding.domain == Domain.POWER_BI
            or request.understanding.task_type
            in {
                TaskType.SEMANTIC_MODEL_QUERY,
                TaskType.SEMANTIC_MODEL_INSPECTION,
                TaskType.DAX_QUERY,
            }
        )

    def capabilities(self) -> McpClientCapability:
        return McpClientCapability(
            name=self.name,
            target=self.target,
            supports_preview=True,
            supports_read=True,
            supports_write=False,
            supports_side_effects=False,
            semantic_model_inspection=True,
            table_listing=True,
            measure_listing=True,
            dax_support=True,
            metadata_read=True,
            refresh_support=False,
            model_write_support=False,
            side_effect_support=False,
            default_tool="run_guided_modeling_request",
            supported_tools=[
                "run_guided_modeling_request",
                "list_semantic_model_tables",
                "list_semantic_model_measures",
                "preview_dax",
            ],
            notes=[
                "Phase 3 orchestration uses safe semantic-model inspection and preview workflows.",
                "Refresh and model mutation remain blocked by execution policy by default.",
            ],
        )

    async def execute(self, request: SpecialistExecutionRequest) -> SpecialistExecutionResult:
        started_at = perf_counter()
        server = self.server_catalog.get(self.name)
        if server is None:
            return self._missing_server_result(request, started_at)

        response = await self.tool_runner.call_tool(
            server,
            request.tool_name,
            request.arguments,
        )
        duration_ms = (perf_counter() - started_at) * 1000
        status = ResultStatus.ERROR if response.is_error else ResultStatus.SUCCESS
        errors = self._errors(response) if response.is_error else []

        return SpecialistExecutionResult(
            mcp_name=self.name,
            target=self.target,
            status=status,
            summary=self._summary(response),
            structured_data=self._structured_data(response),
            sources_used=self._sources(request),
            trace=[
                f"Power BI MCP called tool {request.tool_name}.",
                "Power BI orchestration used policy-controlled semantic execution.",
            ],
            errors=errors,
            warnings=self._warnings(request),
            duration_ms=duration_ms,
            debug={
                "server_name": response.server_name,
                "tool_name": response.tool_name,
                "arguments": request.arguments,
                "policy_decision": request.policy_decision.model_dump(mode="json")
                if request.policy_decision
                else None,
                "raw_result": response.raw_result,
            },
        )

    def _missing_server_result(
        self,
        request: SpecialistExecutionRequest,
        started_at: float,
    ) -> SpecialistExecutionResult:
        duration_ms = (perf_counter() - started_at) * 1000
        return SpecialistExecutionResult(
            mcp_name=self.name,
            target=self.target,
            status=ResultStatus.ERROR,
            summary="Power BI MCP server was not found in the local catalog.",
            structured_data=None,
            sources_used=self._sources(request),
            trace=["Power BI MCP catalog lookup failed."],
            errors=["MCP server not found: power_bi"],
            warnings=[],
            duration_ms=duration_ms,
            debug={"server_name": self.name},
        )

    def _summary(self, response: McpToolCallResponse) -> str:
        if response.is_error:
            return "Power BI MCP returned an error."
        if response.content:
            return response.content[0][:500]
        return "Power BI MCP produced a semantic-model response."

    def _structured_data(self, response: McpToolCallResponse) -> dict[str, Any] | list[Any] | None:
        if response.structured_content is not None:
            return response.structured_content
        if response.content:
            return {"content": response.content}
        return None

    def _errors(self, response: McpToolCallResponse) -> list[str]:
        if response.content:
            return response.content
        return ["Power BI MCP tool call failed."]

    def _sources(self, request: SpecialistExecutionRequest) -> list[str]:
        return list(
            dict.fromkeys(
                item.source_path
                for item in request.enriched_request.retrieved_context.items
            )
        )

    def _warnings(self, request: SpecialistExecutionRequest) -> list[str]:
        warnings = list(request.policy_decision.warnings) if request.policy_decision else []
        if not request.enriched_request.retrieved_context.items:
            warnings.append("No local context item was retrieved before Power BI execution.")
        return warnings
