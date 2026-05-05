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
from mcp_orchestrator.domain.models import McpToolCallResponse
from mcp_orchestrator.infrastructure.audit import SqliteAuditStore
from mcp_orchestrator.infrastructure.context import LocalContextRetriever
from mcp_orchestrator.infrastructure.mcp_clients import DefaultMcpClientRegistry
from mcp_orchestrator.infrastructure.mcp_servers import LocalMcpServerCatalog, McpServerDefinition
from mcp_orchestrator.normalization import DefaultResponseNormalizer


class FakeToolRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def list_tools(self, server: McpServerDefinition):
        return []

    async def call_tool(
        self,
        server: McpServerDefinition,
        tool_name: str,
        arguments: dict[str, object],
    ) -> McpToolCallResponse:
        self.calls.append((tool_name, arguments))
        return McpToolCallResponse(
            server_name=server.name,
            tool_name=tool_name,
            is_error=False,
            content=["ok"],
            structured_content={"arguments": arguments},
            raw_result={"transport": "stdio"},
        )


def build_client(tmp_path: Path) -> tuple[TestClient, FakeToolRunner]:
    server_catalog = LocalMcpServerCatalog(Path("mcps"))
    tool_runner = FakeToolRunner()
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
        audit_store=SqliteAuditStore(tmp_path / "audit.sqlite3"),
    )
    app = FastAPI()
    app.include_router(create_api_router(service))
    return TestClient(app), tool_runner


def test_audit_endpoint_returns_recorded_orchestration(tmp_path: Path) -> None:
    client, _ = build_client(tmp_path)

    response = client.post(
        "/orchestrate",
        json={
            "message": "Use PostgreSQL to prepare safe SQL for monthly revenue.",
            "domain_hint": "postgresql",
            "tags": ["postgresql"],
        },
    )
    correlation_id = response.json()["correlation_id"]

    audit = client.get(f"/audit/{correlation_id}")

    assert audit.status_code == 200
    assert audit.json()["correlation_id"] == correlation_id
    assert audit.json()["payload"]["request"]["domain_hint"] == "postgresql"


def test_confirmation_endpoint_executes_pending_read_only_request(tmp_path: Path) -> None:
    client, runner = build_client(tmp_path)

    preview = client.post(
        "/orchestrate",
        json={
            "message": "Read rows from PostgreSQL sales_orders.",
            "domain_hint": "postgresql",
            "tags": ["postgresql"],
        },
    )
    confirmation_id = preview.json()["confirmation_id"]

    executed = client.post(f"/confirmations/{confirmation_id}/execute")

    assert executed.status_code == 200
    assert executed.json()["status"] == "executed"
    assert runner.calls[-1][1]["auto_execute"] is True
