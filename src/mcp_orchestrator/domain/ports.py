from __future__ import annotations

from typing import Any, Protocol

from .enums import McpTarget
from .models import (
    EnrichedRequest,
    ExecutionPlan,
    NormalizedResponse,
    RequestUnderstanding,
    RetrievedContext,
    SpecialistExecutionRequest,
    SpecialistExecutionResult,
    UserRequest,
)


class RequestUnderstandingService(Protocol):
    def understand(self, request: UserRequest) -> RequestUnderstanding:
        ...


class ContextRetriever(Protocol):
    def retrieve(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> RetrievedContext:
        ...

    def rebuild(self) -> None:
        ...

    def status(self) -> dict[str, Any]:
        ...


class ContextComposer(Protocol):
    def compose(
        self,
        correlation_id: str,
        request: UserRequest,
        understanding: RequestUnderstanding,
        retrieved_context: RetrievedContext,
    ) -> EnrichedRequest:
        ...


class BaseMCPClient(Protocol):
    name: str
    target: McpTarget

    def can_handle(self, plan: ExecutionPlan, request: EnrichedRequest) -> bool:
        ...

    async def execute(self, request: SpecialistExecutionRequest) -> SpecialistExecutionResult:
        ...


class McpClientRegistry(Protocol):
    def all(self) -> list[BaseMCPClient]:
        ...

    def get(self, target: McpTarget) -> BaseMCPClient | None:
        ...


class ExecutionPlanningStrategy(Protocol):
    def create_plan(
        self,
        enriched_request: EnrichedRequest,
        registry: McpClientRegistry,
    ) -> ExecutionPlan:
        ...


class ResponseNormalizer(Protocol):
    def normalize(
        self,
        correlation_id: str,
        results: list[SpecialistExecutionResult],
        timings: dict[str, float],
    ) -> NormalizedResponse:
        ...


# Compatibility protocol names.
RequestInterpreter = RequestUnderstandingService
RagRetriever = ContextRetriever
McpClient = BaseMCPClient
RoutingStrategy = ExecutionPlanningStrategy
