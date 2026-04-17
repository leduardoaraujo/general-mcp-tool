from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mcp_orchestrator.api import create_api_router
from mcp_orchestrator.application import (
    DefaultContextComposer,
    HeuristicRequestInterpreter,
    McpRouter,
)
from mcp_orchestrator.application.orchestrator import OrchestrationService
from mcp_orchestrator.domain.models import McpToolCallResponse, McpToolDefinition
from mcp_orchestrator.infrastructure.mcp_clients import DefaultMcpClientRegistry
from mcp_orchestrator.infrastructure.mcp_servers import LocalMcpServerCatalog, McpServerDefinition
from mcp_orchestrator.infrastructure.rag import TextualRagRetriever
from mcp_orchestrator.normalization import DefaultResponseNormalizer


class FakeToolRunner:
    async def list_tools(self, server: McpServerDefinition) -> list[McpToolDefinition]:
        return [
            McpToolDefinition(
                name="pg_list_tables",
                description="List tables",
                input_schema={"type": "object"},
            )
        ]

    async def call_tool(
        self,
        server: McpServerDefinition,
        tool_name: str,
        arguments: dict[str, object],
    ) -> McpToolCallResponse:
        return McpToolCallResponse(
            server_name=server.name,
            tool_name=tool_name,
            is_error=False,
            content=["ok"],
            structured_content={"arguments": arguments},
            raw_result={"isError": False},
        )


def build_client() -> TestClient:
    service = OrchestrationService(
        interpreter=HeuristicRequestInterpreter(),
        retriever=TextualRagRetriever(Path("docs")),
        composer=DefaultContextComposer(),
        router=McpRouter(DefaultMcpClientRegistry()),
        normalizer=DefaultResponseNormalizer(),
        server_catalog=LocalMcpServerCatalog(Path("mcps")),
        tool_runner=FakeToolRunner(),  # type: ignore[arg-type]
        rag_top_k=5,
    )
    app = FastAPI()
    app.include_router(create_api_router(service))
    return TestClient(app)


def test_list_mcp_tools_endpoint() -> None:
    client = build_client()

    response = client.get("/mcp-servers/postgresql/tools")

    assert response.status_code == 200
    assert response.json()[0]["name"] == "pg_list_tables"


def test_call_mcp_tool_endpoint() -> None:
    client = build_client()

    response = client.post(
        "/mcp-servers/postgresql/tools/pg_list_tables",
        json={"arguments": {"schema_name": "public"}},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["server_name"] == "postgresql"
    assert body["tool_name"] == "pg_list_tables"
    assert body["structured_content"]["arguments"]["schema_name"] == "public"
