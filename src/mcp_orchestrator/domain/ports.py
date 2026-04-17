from __future__ import annotations

from typing import Any, Protocol

from .models import (
    EnrichedRequest,
    MCPResult,
    NormalizedResponse,
    OrchestrateRequest,
    RagContext,
    RequestInterpretation,
)


class RequestInterpreter(Protocol):
    def interpret(self, request: OrchestrateRequest) -> RequestInterpretation:
        ...


class RagRetriever(Protocol):
    def retrieve(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> RagContext:
        ...

    def rebuild(self) -> None:
        ...

    def status(self) -> dict[str, Any]:
        ...


class ContextComposer(Protocol):
    def compose(
        self,
        correlation_id: str,
        request: OrchestrateRequest,
        interpretation: RequestInterpretation,
        rag_context: RagContext,
    ) -> EnrichedRequest:
        ...


class McpClient(Protocol):
    name: str

    def can_handle(self, enriched_request: EnrichedRequest) -> bool:
        ...

    async def execute(self, enriched_request: EnrichedRequest) -> MCPResult:
        ...


class McpClientRegistry(Protocol):
    def all(self) -> list[McpClient]:
        ...

    def get(self, name: str) -> McpClient | None:
        ...


class RoutingStrategy(Protocol):
    def select_clients(
        self,
        enriched_request: EnrichedRequest,
        registry: McpClientRegistry,
    ) -> list[McpClient]:
        ...


class ResponseNormalizer(Protocol):
    def normalize(
        self,
        correlation_id: str,
        results: list[MCPResult],
        timings: dict[str, float],
    ) -> NormalizedResponse:
        ...
