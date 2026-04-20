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


class PostgreSqlMcpClient:
    name = "postgresql"
    target = McpTarget.POSTGRESQL

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
            or request.understanding.domain == Domain.POSTGRESQL
            or request.understanding.task_type == TaskType.SQL_QUERY
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
                "pg_execute_query",
                "pg_list_tables",
                "pg_describe_table",
            ],
            notes=["Phase 1 orchestration uses preview-first guided queries."],
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
        warnings = self._warnings(request)

        return SpecialistExecutionResult(
            mcp_name=self.name,
            target=self.target,
            status=status,
            summary=self._summary(response),
            structured_data=self._structured_data(response),
            sources_used=self._sources(request),
            trace=[
                f"PostgreSQL MCP called tool {request.tool_name}.",
                "PostgreSQL orchestration used preview-only execution.",
            ],
            errors=errors,
            warnings=warnings,
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
            summary="PostgreSQL MCP server was not found in the local catalog.",
            structured_data=None,
            sources_used=self._sources(request),
            trace=["PostgreSQL MCP catalog lookup failed."],
            errors=["MCP server not found: postgresql"],
            warnings=[],
            duration_ms=duration_ms,
            debug={"server_name": self.name},
        )

    def _summary(self, response: McpToolCallResponse) -> str:
        if response.is_error:
            return "PostgreSQL MCP returned an error."
        if response.content:
            return response.content[0][:500]
        return "PostgreSQL MCP produced a preview response."

    def _structured_data(self, response: McpToolCallResponse) -> dict[str, Any] | list[Any] | None:
        if response.structured_content is not None:
            return response.structured_content
        if response.content:
            return {"content": response.content}
        return None

    def _errors(self, response: McpToolCallResponse) -> list[str]:
        if response.content:
            return response.content
        return ["PostgreSQL MCP tool call failed."]

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
            warnings.append("No local context item was retrieved before PostgreSQL execution.")
        if request.arguments.get("auto_execute") is False:
            warnings.append("PostgreSQL request was executed in preview-only mode.")
        return warnings
