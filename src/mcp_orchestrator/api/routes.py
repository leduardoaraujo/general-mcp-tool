from __future__ import annotations

from fastapi import APIRouter, HTTPException

from mcp_orchestrator.application.orchestrator import OrchestrationService
from mcp_orchestrator.domain.models import (
    McpToolCallRequest,
    McpToolCallResponse,
    McpToolDefinition,
    NormalizedResponse,
    OrchestrateRequest,
)


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

    @router.get("/mcp-servers/{server_name}/tools", response_model=list[McpToolDefinition])
    async def list_mcp_tools(server_name: str) -> list[McpToolDefinition]:
        try:
            return await service.list_mcp_tools(server_name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.post(
        "/mcp-servers/{server_name}/tools/{tool_name}",
        response_model=McpToolCallResponse,
    )
    async def call_mcp_tool(
        server_name: str,
        tool_name: str,
        request: McpToolCallRequest,
    ) -> McpToolCallResponse:
        try:
            return await service.call_mcp_tool(server_name, tool_name, request.arguments)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return router
