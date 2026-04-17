from __future__ import annotations

from fastapi import APIRouter

from mcp_orchestrator.application.orchestrator import OrchestrationService
from mcp_orchestrator.domain.models import NormalizedResponse, OrchestrateRequest


def create_api_router(service: OrchestrationService) -> APIRouter:
    router = APIRouter()

    @router.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "mcp_orchestrator"}

    @router.post("/orchestrate", response_model=NormalizedResponse)
    async def orchestrate(request: OrchestrateRequest) -> NormalizedResponse:
        return await service.orchestrate(request)

    @router.get("/docs-index/status")
    async def docs_index_status() -> dict[str, object]:
        return service.docs_index_status()

    @router.post("/docs-index/rebuild")
    async def rebuild_docs_index() -> dict[str, object]:
        return service.rebuild_docs_index()

    @router.get("/mcp-servers/status")
    async def mcp_servers_status() -> dict[str, object]:
        return service.mcp_servers_status()

    return router
