from __future__ import annotations

from uuid import uuid4

from mcp_orchestrator.config import Settings
from mcp_orchestrator.domain.models import NormalizedResponse, OrchestrateRequest
from mcp_orchestrator.domain.ports import (
    ContextComposer,
    RagRetriever,
    RequestInterpreter,
    ResponseNormalizer,
)
from mcp_orchestrator.infrastructure.mcp_clients import DefaultMcpClientRegistry
from mcp_orchestrator.infrastructure.mcp_servers import LocalMcpServerCatalog
from mcp_orchestrator.infrastructure.rag import TextualRagRetriever
from mcp_orchestrator.normalization import DefaultResponseNormalizer
from mcp_orchestrator.observability import TimingRecorder, get_logger, log_stage

from .composer import DefaultContextComposer
from .intake import HeuristicRequestInterpreter
from .routing import McpRouter


class OrchestrationService:
    def __init__(
        self,
        *,
        interpreter: RequestInterpreter,
        retriever: RagRetriever,
        composer: ContextComposer,
        router: McpRouter,
        normalizer: ResponseNormalizer,
        server_catalog: LocalMcpServerCatalog,
        rag_top_k: int,
    ) -> None:
        self.interpreter = interpreter
        self.retriever = retriever
        self.composer = composer
        self.router = router
        self.normalizer = normalizer
        self.server_catalog = server_catalog
        self.rag_top_k = rag_top_k
        self.logger = get_logger(__name__)

    async def orchestrate(self, request: OrchestrateRequest) -> NormalizedResponse:
        correlation_id = str(uuid4())
        timing = TimingRecorder()

        started_at = timing.start()
        interpretation = self.interpreter.interpret(request)
        self._log(correlation_id, "intake", timing.stop("intake", started_at))

        started_at = timing.start()
        rag_context = self.retriever.retrieve(
            request.message,
            filters=self._rag_filters(request, interpretation),
            limit=self.rag_top_k,
        )
        self._log(correlation_id, "rag", timing.stop("rag", started_at))

        started_at = timing.start()
        enriched = self.composer.compose(correlation_id, request, interpretation, rag_context)
        self._log(correlation_id, "compose", timing.stop("compose", started_at))

        started_at = timing.start()
        clients, routing_trace = self.router.select_clients(enriched)
        self._log(
            correlation_id,
            "routing",
            timing.stop("routing", started_at),
            {"selected_clients": [client.name for client in clients]},
        )

        started_at = timing.start()
        results = await self.router.execute_clients(enriched, clients, routing_trace)
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

    def _rag_filters(
        self,
        request: OrchestrateRequest,
        interpretation,
    ) -> dict[str, object]:
        filters: dict[str, object] = {}
        if request.tags:
            filters["tags"] = request.tags
        if interpretation.domain.value not in {"analytics", "general", "unknown"}:
            filters["domain"] = interpretation.domain.value
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
    registry = DefaultMcpClientRegistry()
    router = McpRouter(registry)
    retriever = TextualRagRetriever(
        settings.resolved_docs_dir(),
        chunk_size=settings.rag_chunk_size,
    )
    server_catalog = LocalMcpServerCatalog(settings.resolved_mcps_dir())
    return OrchestrationService(
        interpreter=HeuristicRequestInterpreter(),
        retriever=retriever,
        composer=DefaultContextComposer(),
        router=router,
        normalizer=DefaultResponseNormalizer(),
        server_catalog=server_catalog,
        rag_top_k=settings.rag_top_k,
    )
