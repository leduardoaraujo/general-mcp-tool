from __future__ import annotations

import asyncio
from time import perf_counter

from mcp_orchestrator.domain.enums import ResultStatus
from mcp_orchestrator.domain.models import EnrichedRequest, MCPResult
from mcp_orchestrator.domain.ports import McpClient, McpClientRegistry, RoutingStrategy


class HeuristicRoutingStrategy(RoutingStrategy):
    def select_clients(
        self,
        enriched_request: EnrichedRequest,
        registry: McpClientRegistry,
    ) -> list[McpClient]:
        selected: list[McpClient] = []
        for target in enriched_request.interpretation.candidate_mcps:
            client = registry.get(target.value)
            if client and client.can_handle(enriched_request):
                selected.append(client)

        if selected:
            return selected

        return [
            client
            for client in registry.all()
            if client.can_handle(enriched_request)
        ]


class McpRouter:
    def __init__(
        self,
        registry: McpClientRegistry,
        strategy: RoutingStrategy | None = None,
    ) -> None:
        self.registry = registry
        self.strategy = strategy or HeuristicRoutingStrategy()

    def select_clients(self, enriched_request: EnrichedRequest) -> tuple[list[McpClient], list[str]]:
        clients = self.strategy.select_clients(enriched_request, self.registry)
        trace = [
            f"Selected {client.name} for {enriched_request.interpretation.task_type.value}."
            for client in clients
        ]
        if not trace:
            trace.append("No MCP client selected by routing strategy.")
        return clients, trace

    async def execute_clients(
        self,
        enriched_request: EnrichedRequest,
        clients: list[McpClient],
        routing_trace: list[str],
    ) -> list[MCPResult]:
        if not clients:
            return [self._no_client_result(routing_trace)]

        return await asyncio.gather(
            *[self._safe_execute(client, enriched_request, routing_trace) for client in clients]
        )

    async def _safe_execute(
        self,
        client: McpClient,
        enriched_request: EnrichedRequest,
        routing_trace: list[str],
    ) -> MCPResult:
        start = perf_counter()
        try:
            result = await client.execute(enriched_request)
            result.trace[:0] = routing_trace
            return result
        except Exception as exc:
            duration_ms = (perf_counter() - start) * 1000
            return MCPResult(
                mcp_name=client.name,
                status=ResultStatus.ERROR,
                summary=f"{client.name} failed during execution.",
                raw_output={},
                structured_data=None,
                sources_used=[],
                trace=[*routing_trace, f"{client.name} raised {type(exc).__name__}."],
                errors=[str(exc)],
                warnings=[],
                duration_ms=duration_ms,
            )

    def _no_client_result(self, routing_trace: list[str]) -> MCPResult:
        return MCPResult(
            mcp_name="router",
            status=ResultStatus.ERROR,
            summary="No MCP client could handle the enriched request.",
            raw_output={},
            structured_data=None,
            sources_used=[],
            trace=routing_trace,
            errors=["No MCP client selected."],
            warnings=[],
            duration_ms=0,
        )
