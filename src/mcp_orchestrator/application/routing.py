from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Any

from mcp_orchestrator.domain.enums import ExecutionMode, McpTarget, ResultStatus
from mcp_orchestrator.domain.models import (
    EnrichedRequest,
    ExecutionPlan,
    SpecialistExecutionRequest,
    SpecialistExecutionResult,
)
from mcp_orchestrator.domain.ports import BaseMCPClient, ExecutionPlanningStrategy, McpClientRegistry


class HeuristicExecutionPlanningStrategy(ExecutionPlanningStrategy):
    def create_plan(
        self,
        enriched_request: EnrichedRequest,
        registry: McpClientRegistry,
    ) -> ExecutionPlan:
        targets = self._available_targets(enriched_request, registry)
        mode = self._execution_mode(targets)
        trace = self._trace(enriched_request, targets, mode)
        return ExecutionPlan(
            correlation_id=enriched_request.correlation_id,
            target_mcps=targets,
            execution_mode=mode,
            tool_hints=self._tool_hints(targets),
            trace=trace,
        )

    def _available_targets(
        self,
        enriched_request: EnrichedRequest,
        registry: McpClientRegistry,
    ) -> list[McpTarget]:
        selected: list[McpTarget] = []
        for target in enriched_request.understanding.candidate_mcps:
            if registry.get(target):
                selected.append(target)

        if selected:
            return selected

        return [
            client.target
            for client in registry.all()
            if client.can_handle(
                ExecutionPlan(
                    correlation_id=enriched_request.correlation_id,
                    target_mcps=[],
                    execution_mode=ExecutionMode.SIMPLE,
                ),
                enriched_request,
            )
        ]

    def _execution_mode(self, targets: list[McpTarget]) -> ExecutionMode:
        if targets == [McpTarget.POSTGRESQL]:
            return ExecutionMode.PREVIEW_ONLY
        if len(targets) > 1:
            return ExecutionMode.PARALLEL
        return ExecutionMode.SIMPLE

    def _tool_hints(self, targets: list[McpTarget]) -> dict[McpTarget, str]:
        hints: dict[McpTarget, str] = {}
        if McpTarget.POSTGRESQL in targets:
            hints[McpTarget.POSTGRESQL] = "run_guided_query"
        return hints

    def _trace(
        self,
        enriched_request: EnrichedRequest,
        targets: list[McpTarget],
        mode: ExecutionMode,
    ) -> list[str]:
        if not targets:
            return ["No MCP client selected by execution planning strategy."]
        return [
            (
                f"Selected {target.value} for "
                f"{enriched_request.understanding.task_type.value} using {mode.value} mode."
            )
            for target in targets
        ]


class ExecutionRouter:
    def __init__(
        self,
        registry: McpClientRegistry,
        strategy: ExecutionPlanningStrategy | None = None,
    ) -> None:
        self.registry = registry
        self.strategy = strategy or HeuristicExecutionPlanningStrategy()

    def create_plan(self, enriched_request: EnrichedRequest) -> ExecutionPlan:
        return self.strategy.create_plan(enriched_request, self.registry)

    def select_clients(self, enriched_request: EnrichedRequest) -> tuple[list[BaseMCPClient], list[str]]:
        plan = self.create_plan(enriched_request)
        clients = self._clients_for_plan(plan, enriched_request)
        return clients, plan.trace

    async def execute_plan(
        self,
        enriched_request: EnrichedRequest,
        plan: ExecutionPlan,
    ) -> list[SpecialistExecutionResult]:
        clients = self._clients_for_plan(plan, enriched_request)
        if not clients:
            return [self._no_client_result(plan)]

        requests = [
            self._specialist_request(enriched_request, plan, client)
            for client in clients
        ]
        return await asyncio.gather(
            *[
                self._safe_execute(client, request, plan.trace)
                for client, request in zip(clients, requests, strict=True)
            ]
        )

    async def execute_clients(
        self,
        enriched_request: EnrichedRequest,
        clients: list[BaseMCPClient],
        routing_trace: list[str],
    ) -> list[SpecialistExecutionResult]:
        plan = ExecutionPlan(
            correlation_id=enriched_request.correlation_id,
            target_mcps=[client.target for client in clients],
            execution_mode=ExecutionMode.PARALLEL if len(clients) > 1 else ExecutionMode.SIMPLE,
            trace=routing_trace,
        )
        return await self.execute_plan(enriched_request, plan)

    def _clients_for_plan(
        self,
        plan: ExecutionPlan,
        enriched_request: EnrichedRequest,
    ) -> list[BaseMCPClient]:
        clients: list[BaseMCPClient] = []
        for target in plan.target_mcps:
            client = self.registry.get(target)
            if client and client.can_handle(plan, enriched_request):
                clients.append(client)
        return clients

    def _specialist_request(
        self,
        enriched_request: EnrichedRequest,
        plan: ExecutionPlan,
        client: BaseMCPClient,
    ) -> SpecialistExecutionRequest:
        tool_name = plan.tool_hints.get(client.target, "execute")
        return SpecialistExecutionRequest(
            correlation_id=enriched_request.correlation_id,
            target=client.target,
            tool_name=tool_name,
            arguments=self._arguments_for_target(enriched_request, plan, client.target),
            enriched_request=enriched_request,
            execution_plan=plan,
        )

    def _arguments_for_target(
        self,
        enriched_request: EnrichedRequest,
        plan: ExecutionPlan,
        target: McpTarget,
    ) -> dict[str, Any]:
        if target == McpTarget.POSTGRESQL:
            return {
                "question": self._postgres_question(enriched_request),
                "auto_execute": False,
                "limit": 100,
            }
        return {
            "intent": enriched_request.understanding.intent,
            "mode": plan.execution_mode.value,
        }

    def _postgres_question(self, enriched_request: EnrichedRequest) -> str:
        context_lines = [
            f"- {item.source_path}: {item.content[:500]}"
            for item in enriched_request.retrieved_context.items
        ]
        constraints = enriched_request.constraints or ["Preview only. Do not execute data retrieval."]
        return "\n".join(
            [
                "Prepare a safe PostgreSQL SQL preview for this enriched request.",
                f"Original user request: {enriched_request.original_request}",
                f"Intent: {enriched_request.understanding.intent}",
                f"Task type: {enriched_request.understanding.task_type.value}",
                "Constraints:",
                *[f"- {constraint}" for constraint in constraints],
                "Retrieved local context:",
                *(context_lines or ["- No local context was retrieved."]),
            ]
        )

    async def _safe_execute(
        self,
        client: BaseMCPClient,
        request: SpecialistExecutionRequest,
        routing_trace: list[str],
    ) -> SpecialistExecutionResult:
        start = perf_counter()
        try:
            result = await client.execute(request)
            result.trace[:0] = routing_trace
            return result
        except Exception as exc:
            duration_ms = (perf_counter() - start) * 1000
            return SpecialistExecutionResult(
                mcp_name=client.name,
                target=client.target,
                status=ResultStatus.ERROR,
                summary=f"{client.name} failed during execution.",
                structured_data=None,
                sources_used=self._sources(request),
                trace=[*routing_trace, f"{client.name} raised {type(exc).__name__}."],
                errors=[str(exc)],
                warnings=[],
                duration_ms=duration_ms,
                debug={},
            )

    def _no_client_result(self, plan: ExecutionPlan) -> SpecialistExecutionResult:
        return SpecialistExecutionResult(
            mcp_name="router",
            target=None,
            status=ResultStatus.ERROR,
            summary="No MCP client could handle the enriched request.",
            structured_data=None,
            sources_used=[],
            trace=plan.trace,
            errors=["No MCP client selected."],
            warnings=[],
            duration_ms=0,
            debug={},
        )

    def _sources(self, request: SpecialistExecutionRequest) -> list[str]:
        return list(
            dict.fromkeys(
                item.source_path
                for item in request.enriched_request.retrieved_context.items
            )
        )


McpRouter = ExecutionRouter
HeuristicRoutingStrategy = HeuristicExecutionPlanningStrategy
