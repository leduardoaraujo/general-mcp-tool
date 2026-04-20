from __future__ import annotations

from uuid import uuid4

from mcp_orchestrator.config import Settings
from mcp_orchestrator.domain.models import (
    McpToolCallResponse,
    McpToolDefinition,
    NormalizedResponse,
    UserRequest,
)
from mcp_orchestrator.domain.ports import (
    ContextComposer,
    ContextRetriever,
    RequestUnderstandingService,
    ResponseNormalizer,
)
from mcp_orchestrator.infrastructure.context import LocalContextRetriever
from mcp_orchestrator.infrastructure.mcp_clients import DefaultMcpClientRegistry
from mcp_orchestrator.infrastructure.mcp_servers import LocalMcpServerCatalog, StdioMcpToolRunner
from mcp_orchestrator.normalization import DefaultResponseNormalizer
from mcp_orchestrator.observability import TimingRecorder, get_logger, log_stage

from .composer import DefaultContextComposer
from .intake import HeuristicRequestUnderstandingService
from .routing import ExecutionRouter


class OrchestrationService:
    def __init__(
        self,
        *,
        understanding_service: RequestUnderstandingService | None = None,
        interpreter: RequestUnderstandingService | None = None,
        retriever: ContextRetriever,
        composer: ContextComposer,
        router: ExecutionRouter,
        normalizer: ResponseNormalizer,
        server_catalog: LocalMcpServerCatalog,
        tool_runner: StdioMcpToolRunner,
        rag_top_k: int,
    ) -> None:
        self.understanding_service = understanding_service or interpreter
        if self.understanding_service is None:
            raise ValueError("understanding_service is required.")
        self.retriever = retriever
        self.composer = composer
        self.router = router
        self.normalizer = normalizer
        self.server_catalog = server_catalog
        self.tool_runner = tool_runner
        self.rag_top_k = rag_top_k
        self.logger = get_logger(__name__)

    async def orchestrate(self, request: UserRequest) -> NormalizedResponse:
        correlation_id = str(uuid4())
        timing = TimingRecorder()

        started_at = timing.start()
        understanding = self.understanding_service.understand(request)
        self._log(correlation_id, "intake", timing.stop("intake", started_at))

        started_at = timing.start()
        retrieved_context = self.retriever.retrieve(
            request.message,
            filters=self._context_filters(request, understanding),
            limit=self.rag_top_k,
        )
        self._log(correlation_id, "context_retrieval", timing.stop("context_retrieval", started_at))

        started_at = timing.start()
        enriched = self.composer.compose(correlation_id, request, understanding, retrieved_context)
        self._log(correlation_id, "compose", timing.stop("compose", started_at))

        started_at = timing.start()
        plan = self.router.create_plan(enriched)
        self._log(
            correlation_id,
            "planning",
            timing.stop("planning", started_at),
            {"selected_targets": [target.value for target in plan.target_mcps]},
        )

        started_at = timing.start()
        results = await self.router.execute_plan(enriched, plan)
        self._log(correlation_id, "mcp_execution", timing.stop("mcp_execution", started_at))

        started_at = timing.start()
        response = self.normalizer.normalize(correlation_id, results, timing.timings)
        duration_ms = timing.stop("normalization", started_at)
        response.timings["normalization"] = round(duration_ms, 3)
        self._log(correlation_id, "normalization", duration_ms, {"status": response.status.value})
        return response

    def docs_index_status(self) -> dict[str, object]:
        return self.retriever.status()

    def rebuild_docs_index(self) -> dict[str, object]:
        self.retriever.rebuild()
        return self.retriever.status()

    def mcp_servers_status(self) -> dict[str, object]:
        return self.server_catalog.status()

    async def list_mcp_tools(self, server_name: str) -> list[McpToolDefinition]:
        server = self.server_catalog.get(server_name)
        if not server:
            raise ValueError(f"MCP server not found: {server_name}")
        return await self.tool_runner.list_tools(server)

    async def call_mcp_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, object],
    ) -> McpToolCallResponse:
        server = self.server_catalog.get(server_name)
        if not server:
            raise ValueError(f"MCP server not found: {server_name}")
        return await self.tool_runner.call_tool(server, tool_name, arguments)

    def _context_filters(self, request: UserRequest, understanding) -> dict[str, object]:
        filters: dict[str, object] = {}
        if request.tags:
            filters["tags"] = request.tags
        if understanding.domain.value not in {"analytics", "general", "unknown"}:
            filters["domain"] = understanding.domain.value
        return filters

    def _log(
        self,
        correlation_id: str,
        stage: str,
        duration_ms: float,
        extra: dict[str, object] | None = None,
    ) -> None:
        log_stage(
            self.logger,
            correlation_id=correlation_id,
            stage=stage,
            status=(extra or {}).pop("status", "success"),
            duration_ms=duration_ms,
            extra=extra,
        )


def create_orchestration_service(settings: Settings | None = None) -> OrchestrationService:
    settings = settings or Settings()
    server_catalog = LocalMcpServerCatalog(settings.resolved_mcps_dir())
    tool_runner = StdioMcpToolRunner()
    registry = DefaultMcpClientRegistry(
        server_catalog=server_catalog,
        tool_runner=tool_runner,
    )
    router = ExecutionRouter(registry)
    retriever = LocalContextRetriever(
        settings.resolved_docs_dir(),
        chunk_size=settings.rag_chunk_size,
    )
    return OrchestrationService(
        understanding_service=HeuristicRequestUnderstandingService(),
        retriever=retriever,
        composer=DefaultContextComposer(),
        router=router,
        normalizer=DefaultResponseNormalizer(),
        server_catalog=server_catalog,
        tool_runner=tool_runner,
        rag_top_k=settings.rag_top_k,
    )
