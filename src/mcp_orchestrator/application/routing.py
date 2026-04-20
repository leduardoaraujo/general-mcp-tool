from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Any

from mcp_orchestrator.domain.enums import ExecutionMode, McpTarget, ResultStatus, SafetyLevel
from mcp_orchestrator.domain.models import (
    EnrichedRequest,
    ExecutionPlan,
    ExecutionPolicyDecision,
    OrchestrationTrace,
    SpecialistExecutionRequest,
    SpecialistExecutionResult,
)
from mcp_orchestrator.domain.ports import BaseMCPClient, ExecutionPlanningStrategy, McpClientRegistry


class HeuristicExecutionPlanningStrategy(ExecutionPlanningStrategy):
    relational_targets = {McpTarget.POSTGRESQL, McpTarget.SQL_SERVER}

    def create_plan(
        self,
        enriched_request: EnrichedRequest,
        registry: McpClientRegistry,
        policy_decision: ExecutionPolicyDecision | None = None,
    ) -> ExecutionPlan:
        targets = self._available_targets(enriched_request, registry, policy_decision)
        mode = self._execution_mode(targets, policy_decision)
        trace = self._trace(enriched_request, targets, mode)
        if policy_decision:
            trace.extend(policy_decision.trace)
        return ExecutionPlan(
            correlation_id=enriched_request.correlation_id,
            target_mcps=targets,
            execution_mode=mode,
            tool_hints=self._tool_hints(targets),
            policy_decision=policy_decision,
            trace=trace,
        )

    def _available_targets(
        self,
        enriched_request: EnrichedRequest,
        registry: McpClientRegistry,
        policy_decision: ExecutionPolicyDecision | None,
    ) -> list[McpTarget]:
        preferred = enriched_request.understanding.target_preference
        if preferred and self._client_supports_policy(registry.get(preferred), policy_decision):
            return [preferred]

        selected: list[McpTarget] = []
        for target in enriched_request.understanding.candidate_mcps:
            if self._client_supports_policy(registry.get(target), policy_decision):
                selected.append(target)

        if selected:
            return selected

        return [
            client.target
            for client in registry.all()
            if self._client_supports_policy(client, policy_decision)
            if client.can_handle(
                ExecutionPlan(
                    correlation_id=enriched_request.correlation_id,
                    target_mcps=[],
                    execution_mode=ExecutionMode.SIMPLE,
                ),
                enriched_request,
            )
        ]

    def _client_supports_policy(
        self,
        client: BaseMCPClient | None,
        policy_decision: ExecutionPolicyDecision | None,
    ) -> bool:
        if client is None:
            return False
        if policy_decision is None:
            return True

        capabilities = client.capabilities()
        if policy_decision.preview_only:
            return capabilities.supports_preview
        if policy_decision.read_only:
            return capabilities.supports_read
        if policy_decision.write:
            return capabilities.supports_write
        if policy_decision.side_effects:
            return capabilities.supports_side_effects
        return True

    def _execution_mode(
        self,
        targets: list[McpTarget],
        policy_decision: ExecutionPolicyDecision | None,
    ) -> ExecutionMode:
        if policy_decision and policy_decision.preview_only:
            return ExecutionMode.PREVIEW_ONLY
        if len(targets) == 1 and targets[0] in self.relational_targets:
            return ExecutionMode.PREVIEW_ONLY
        if len(targets) > 1:
            return ExecutionMode.PARALLEL
        return ExecutionMode.SIMPLE

    def _tool_hints(self, targets: list[McpTarget]) -> dict[McpTarget, str]:
        hints: dict[McpTarget, str] = {}
        if McpTarget.POSTGRESQL in targets:
            hints[McpTarget.POSTGRESQL] = "run_guided_query"
        if McpTarget.SQL_SERVER in targets:
            hints[McpTarget.SQL_SERVER] = "run_guided_query"
        if McpTarget.POWER_BI in targets:
            hints[McpTarget.POWER_BI] = "run_guided_modeling_request"
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

    def create_plan(
        self,
        enriched_request: EnrichedRequest,
        policy_decision: ExecutionPolicyDecision | None = None,
    ) -> ExecutionPlan:
        return self.strategy.create_plan(enriched_request, self.registry, policy_decision)

    def select_clients(self, enriched_request: EnrichedRequest) -> tuple[list[BaseMCPClient], list[str]]:
        plan = self.create_plan(enriched_request)
        clients = self._clients_for_plan(plan, enriched_request)
        return clients, plan.trace

    async def execute_plan(
        self,
        enriched_request: EnrichedRequest,
        plan: ExecutionPlan,
        orchestration_trace: OrchestrationTrace | None = None,
    ) -> list[SpecialistExecutionResult]:
        if plan.policy_decision and plan.policy_decision.safety_level == SafetyLevel.BLOCKED:
            return [self._policy_blocked_result(enriched_request, plan)]

        clients = self._clients_for_plan(plan, enriched_request)
        if not clients:
            return [self._no_client_result(plan)]

        requests = [
            self._specialist_request(enriched_request, plan, client, orchestration_trace)
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
        orchestration_trace: OrchestrationTrace | None = None,
    ) -> SpecialistExecutionRequest:
        tool_name = plan.tool_hints.get(client.target, "execute")
        return SpecialistExecutionRequest(
            correlation_id=enriched_request.correlation_id,
            target=client.target,
            tool_name=tool_name,
            arguments=self._arguments_for_target(enriched_request, plan, client.target),
            enriched_request=enriched_request,
            execution_plan=plan,
            policy_decision=plan.policy_decision,
            orchestration_trace=orchestration_trace,
        )

    def _arguments_for_target(
        self,
        enriched_request: EnrichedRequest,
        plan: ExecutionPlan,
        target: McpTarget,
    ) -> dict[str, Any]:
        if target in {McpTarget.POSTGRESQL, McpTarget.SQL_SERVER}:
            return {
                "question": self._relational_question(enriched_request, target),
                "auto_execute": self._auto_execute(plan.policy_decision),
                "limit": 100,
            }
        if target == McpTarget.POWER_BI:
            return {
                "request": self._power_bi_request(enriched_request),
                "preview_only": not self._auto_execute(plan.policy_decision),
                "allow_write": self._allow_write(plan.policy_decision),
            }
        return {
            "intent": enriched_request.understanding.intent,
            "mode": plan.execution_mode.value,
        }

    def _power_bi_request(self, enriched_request: EnrichedRequest) -> str:
        context_lines = [
            f"- {item.source_path}: {item.content[:500]}"
            for item in enriched_request.retrieved_context.items
        ]
        constraints = enriched_request.constraints or [
            "Use safe metadata/model inspection or DAX preview only.",
            "Do not refresh or mutate the model unless execution policy explicitly allows it.",
        ]
        return "\n".join(
            [
                "Prepare a safe Power BI semantic-model response for this enriched request.",
                f"Original user request: {enriched_request.original_request}",
                f"Intent: {enriched_request.understanding.intent}",
                f"Task type: {enriched_request.understanding.task_type.value}",
                f"Requested action: {enriched_request.understanding.requested_action.value}",
                "Constraints:",
                *[f"- {constraint}" for constraint in constraints],
                "Retrieved local context:",
                *(context_lines or ["- No local context was retrieved."]),
            ]
        )

    def _relational_question(self, enriched_request: EnrichedRequest, target: McpTarget) -> str:
        context_lines = [
            f"- {item.source_path}: {item.content[:500]}"
            for item in enriched_request.retrieved_context.items
        ]
        constraints = enriched_request.constraints or ["Preview only. Do not execute data retrieval."]
        backend = self._backend_label(target)
        return "\n".join(
            [
                f"Prepare a safe {backend} SQL preview for this enriched request.",
                f"Original user request: {enriched_request.original_request}",
                f"Intent: {enriched_request.understanding.intent}",
                f"Task type: {enriched_request.understanding.task_type.value}",
                f"Requested action: {enriched_request.understanding.requested_action.value}",
                "Constraints:",
                *[f"- {constraint}" for constraint in constraints],
                "Retrieved local context:",
                *(context_lines or ["- No local context was retrieved."]),
            ]
        )

    def _backend_label(self, target: McpTarget) -> str:
        if target == McpTarget.SQL_SERVER:
            return "SQL Server"
        if target == McpTarget.POSTGRESQL:
            return "PostgreSQL"
        return target.value

    def _auto_execute(self, policy_decision: ExecutionPolicyDecision | None) -> bool:
        if not policy_decision:
            return False
        return bool(
            policy_decision.allow_execution
            and policy_decision.read_only
            and not policy_decision.preview_only
            and not policy_decision.write
            and not policy_decision.side_effects
        )

    def _allow_write(self, policy_decision: ExecutionPolicyDecision | None) -> bool:
        if not policy_decision:
            return False
        return bool(
            policy_decision.allow_execution
            and policy_decision.write
            and not policy_decision.side_effects
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

    def _policy_blocked_result(
        self,
        enriched_request: EnrichedRequest,
        plan: ExecutionPlan,
    ) -> SpecialistExecutionResult:
        policy = plan.policy_decision
        blocked_reason = policy.blocked_reason if policy else "Execution policy blocked the request."
        return SpecialistExecutionResult(
            mcp_name="execution_policy",
            target=None,
            status=ResultStatus.ERROR,
            summary="Execution policy blocked specialist execution.",
            structured_data=None,
            sources_used=list(
                dict.fromkeys(item.source_path for item in enriched_request.retrieved_context.items)
            ),
            trace=[*plan.trace, "No specialist MCP was called because policy blocked execution."],
            errors=[blocked_reason or "Execution blocked."],
            warnings=policy.warnings if policy else [],
            duration_ms=0,
            debug={"policy_decision": policy.model_dump(mode="json") if policy else None},
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
