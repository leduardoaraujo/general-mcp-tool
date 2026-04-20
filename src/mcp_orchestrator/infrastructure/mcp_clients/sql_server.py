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


class SqlServerMcpClient:
    name = "sql_server"
    target = McpTarget.SQL_SERVER

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
            or request.understanding.domain == Domain.SQL_SERVER
            or (
                request.understanding.task_type == TaskType.SQL_QUERY
                and request.understanding.target_preference == self.target
            )
        )

    def capabilities(self) -> McpClientCapability:
        return McpClientCapability(
            name=self.name,
            target=self.target,
            supports_preview=True,
            supports_read=True,
            supports_write=False,
            supports_side_effects=False,
            table_listing=True,
            metadata_read=True,
            side_effect_support=False,
            default_tool="run_guided_query",
            supported_tools=[
                "run_guided_query",
                "list_tables",
                "describe_table",
                "execute_query",
            ],
            notes=[
                "Phase 2 orchestration uses preview-first guided queries.",
                "Expected SQL Server MCP tools mirror the relational tool contract.",
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
                f"SQL Server MCP called tool {request.tool_name}.",
                "SQL Server orchestration used policy-controlled relational execution.",
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
            summary="SQL Server MCP server was not found in the local catalog.",
            structured_data=None,
            sources_used=self._sources(request),
            trace=["SQL Server MCP catalog lookup failed."],
            errors=["MCP server not found: sql_server"],
            warnings=[],
            duration_ms=duration_ms,
            debug={"server_name": self.name},
        )

    def _summary(self, response: McpToolCallResponse) -> str:
        if response.is_error:
            return "SQL Server MCP returned an error."
        if response.content:
            return response.content[0][:500]
        return "SQL Server MCP produced a preview response."

    def _structured_data(self, response: McpToolCallResponse) -> dict[str, Any] | list[Any] | None:
        if response.structured_content is not None:
            return response.structured_content
        if response.content:
            return {"content": response.content}
        return None

    def _errors(self, response: McpToolCallResponse) -> list[str]:
        if response.content:
            return response.content
        return ["SQL Server MCP tool call failed."]

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
            warnings.append("No local context item was retrieved before SQL Server execution.")
        if request.arguments.get("auto_execute") is False:
            warnings.append("SQL Server request was executed in preview-only mode.")
        return warnings
