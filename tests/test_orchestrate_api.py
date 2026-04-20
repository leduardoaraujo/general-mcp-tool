from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mcp_orchestrator.api import create_api_router
from mcp_orchestrator.application import (
    DefaultContextComposer,
    ExecutionRouter,
    HeuristicRequestInterpreter,
)
from mcp_orchestrator.application.orchestrator import OrchestrationService
from mcp_orchestrator.config import Settings
from mcp_orchestrator.domain.models import McpToolCallResponse
from mcp_orchestrator.infrastructure.context import LocalContextRetriever
from mcp_orchestrator.infrastructure.mcp_clients import DefaultMcpClientRegistry
from mcp_orchestrator.infrastructure.mcp_servers import LocalMcpServerCatalog, McpServerDefinition
from mcp_orchestrator.main import create_app
from mcp_orchestrator.normalization import DefaultResponseNormalizer


class FakePostgresToolRunner:
    async def list_tools(self, server: McpServerDefinition):
        return []

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
            content=["preview"],
            structured_content={"preview_only": True, "arguments": arguments},
            raw_result={"transport": "stdio"},
        )


def test_health_endpoint() -> None:
    client = TestClient(create_app(Settings()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_orchestrate_endpoint_returns_normalized_response() -> None:
    client = TestClient(create_app(Settings()))

    response = client.post(
        "/orchestrate",
        json={"message": "Show Total Sales from the Power BI semantic model"},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["correlation_id"]
    assert body["summary"]
    assert body["mcp_trace"]
    assert body["raw_outputs"]


def test_orchestrate_postgresql_request_returns_traceable_specialist_response() -> None:
    server_catalog = LocalMcpServerCatalog(Path("mcps"))
    tool_runner = FakePostgresToolRunner()
    service = OrchestrationService(
        interpreter=HeuristicRequestInterpreter(),
        retriever=LocalContextRetriever(Path("docs/context")),
        composer=DefaultContextComposer(),
        router=ExecutionRouter(
            DefaultMcpClientRegistry(
                server_catalog=server_catalog,
                tool_runner=tool_runner,  # type: ignore[arg-type]
            )
        ),
        normalizer=DefaultResponseNormalizer(),
        server_catalog=server_catalog,
        tool_runner=tool_runner,  # type: ignore[arg-type]
        rag_top_k=5,
    )
    app = FastAPI()
    app.include_router(create_api_router(service))
    client = TestClient(app)

    response = client.post(
        "/orchestrate",
        json={
            "message": "Use PostgreSQL to find tables for monthly sales revenue and prepare safe SQL.",
            "domain_hint": "postgresql",
            "tags": ["sales", "postgresql"],
            "metadata": {},
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["specialist_results"]
    assert body["specialist_results"][0]["mcp_name"] == "postgresql"
    assert body["sources_used"]
    assert body["mcp_trace"]
    assert "raw_result" not in body


def test_docs_index_rebuild_updates_status() -> None:
    client = TestClient(create_app(Settings()))

    before = client.get("/docs-index/status").json()
    after = client.post("/docs-index/rebuild").json()

    assert before["document_count"] == after["document_count"]
    assert after["chunk_count"] >= 1
