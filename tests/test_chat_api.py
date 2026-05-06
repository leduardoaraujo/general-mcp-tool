from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mcp_orchestrator.api import create_api_router
from mcp_orchestrator.application import (
    ChatAnswerService,
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
from mcp_orchestrator.main import create_app
from mcp_orchestrator.normalization import DefaultResponseNormalizer
from mcp_orchestrator.config import Settings
from mcp_orchestrator.domain.enums import ResultStatus
from mcp_orchestrator.domain.models import NormalizedResponse, SpecialistExecutionResult, UserRequest


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
            content=["preview"],
            structured_content={"arguments": arguments},
            raw_result={"transport": "stdio"},
        )


def build_client(tmp_path: Path) -> tuple[TestClient, FakeToolRunner]:
    server_catalog = LocalMcpServerCatalog(Path("mcps"))
    runner = FakeToolRunner()
    service = OrchestrationService(
        interpreter=HeuristicRequestInterpreter(),
        retriever=LocalContextRetriever(Path("docs/context")),
        composer=DefaultContextComposer(),
        router=ExecutionRouter(
            DefaultMcpClientRegistry(
                server_catalog=server_catalog,
                tool_runner=runner,  # type: ignore[arg-type]
            )
        ),
        normalizer=DefaultResponseNormalizer(),
        server_catalog=server_catalog,
        tool_runner=runner,  # type: ignore[arg-type]
        rag_top_k=5,
        audit_store=SqliteAuditStore(tmp_path / "audit.sqlite3"),
    )
    app = FastAPI()
    app.include_router(create_api_router(service))
    return TestClient(app), runner


def test_chat_endpoint_wraps_orchestration_response(tmp_path: Path) -> None:
    client, runner = build_client(tmp_path)

    response = client.post(
        "/chat",
        json={
            "message": "Use PostgreSQL to prepare safe SQL.",
            "domain_hint": "postgresql",
            "tags": ["postgresql"],
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["message"]
    assert body["orchestration"]["correlation_id"]
    assert body["sources_used"]
    assert runner.calls[0][0] == "run_guided_query"


def test_chat_confirmation_executes_pending_read_only_request(tmp_path: Path) -> None:
    client, runner = build_client(tmp_path)
    preview = client.post(
        "/chat",
        json={
            "message": "Read rows from PostgreSQL sales_orders.",
            "domain_hint": "postgresql",
            "tags": ["postgresql"],
        },
    )
    confirmation_id = preview.json()["confirmation_id"]

    executed = client.post(f"/chat/confirmations/{confirmation_id}/execute")

    assert executed.status_code == 200
    assert executed.json()["orchestration"]["status"] == "success"
    assert runner.calls[-1][1]["auto_execute"] is True


def test_root_serves_chat_ui(tmp_path: Path) -> None:
    client = TestClient(create_app(Settings(audit_db_path=tmp_path / "audit.sqlite3")))

    response = client.get("/")

    assert response.status_code == 200
    assert "Orquestra MCP" in response.text


def test_chat_fallback_summarizes_open_power_bi_report() -> None:
    response = NormalizedResponse(
        correlation_id="cid",
        status=ResultStatus.SUCCESS,
        summary="MCP Orchestrator completed the request successfully.",
        specialist_results=[
            SpecialistExecutionResult(
                mcp_name="power_bi",
                target="power_bi",
                status=ResultStatus.SUCCESS,
                summary="Found 3 table(s) and 59 measure(s) in the Power BI model.",
                structured_data=None,
                duration_ms=1,
            )
        ],
        structured_data={
            "power_bi": {
                "connection": {
                    "parentWindowTitle": "Pjs",
                    "parentProcessName": "PBIDesktop",
                    "port": 64842,
                },
                "tables": [{"name": "PJs"}, {"name": "Medidas"}, {"name": "Calendario"}],
                "measures": [{"name": "Total Contratos"}, {"name": "Total Distratos"}],
            }
        },
        sources_used=["docs/context/business_rules/power_bi/semantic-model-inspection.md"],
    )

    chat = ChatAnswerService(api_key=None, model="fallback").compose(
        request=UserRequest(message="Qual relatorio esta aberto?"),
        orchestration=response,
    )

    assert "Relatorio Power BI aberto: Pjs." in chat.message
    assert "Tabelas encontradas (3): PJs, Medidas, Calendario." in chat.message
    assert "Medidas encontradas: 2." in chat.message


def test_chat_fallback_lists_power_bi_measure_names_when_requested() -> None:
    response = NormalizedResponse(
        correlation_id="cid",
        status=ResultStatus.SUCCESS,
        summary="MCP Orchestrator completed the request successfully.",
        specialist_results=[],
        structured_data={
            "power_bi": {
                "connection": {
                    "parentWindowTitle": "Pjs",
                    "parentProcessName": "PBIDesktop",
                    "port": 64842,
                },
                "measures": [{"name": "Total Contratos"}, {"name": "Total Distratos"}],
            }
        },
    )

    chat = ChatAnswerService(api_key=None, model="fallback").compose(
        request=UserRequest(message="Quais sao as minhas medidas?"),
        orchestration=response,
    )

    assert "Medidas encontradas (2): Total Contratos, Total Distratos." in chat.message


def test_chat_fallback_lists_power_bi_columns_and_measure_definitions() -> None:
    response = NormalizedResponse(
        correlation_id="cid",
        status=ResultStatus.SUCCESS,
        summary="MCP Orchestrator completed the request successfully.",
        specialist_results=[],
        structured_data={
            "power_bi": {
                "connection": {
                    "parentWindowTitle": "Pjs",
                    "parentProcessName": "PBIDesktop",
                    "port": 64842,
                },
                "columns": {
                    "PJs": [{"name": "Contrato"}, {"name": "Status"}],
                },
                "measure_definitions": [
                    {
                        "tableName": "Medidas",
                        "name": "Total Contratos",
                        "expression": "COUNTROWS(PJs)",
                    }
                ],
            }
        },
    )

    chat = ChatAnswerService(api_key=None, model="fallback").compose(
        request=UserRequest(message="Me mostre a definicao da medida Total Contratos"),
        orchestration=response,
    )

    assert "Colunas da tabela PJs (2): Contrato, Status." in chat.message
    assert "- Total Contratos (Medidas): COUNTROWS(PJs)" in chat.message


def test_chat_fallback_formats_power_bi_ranking_validation() -> None:
    response = NormalizedResponse(
        correlation_id="cid",
        status=ResultStatus.SUCCESS,
        summary="Executed Power BI DAX validation successfully.",
        specialist_results=[],
        structured_data={
            "power_bi": {
                "connection": {
                    "parentWindowTitle": "Top_Atual2",
                    "parentProcessName": "PBIDesktop",
                    "port": 59167,
                },
                "ranking_analysis": {
                    "entity_type": "liner",
                    "entity_name": "THIAGO MORAES BARBOSA",
                    "measure_name": "Propostas VGV",
                    "entity_value": "22720675,050000004",
                    "entity_rank": 160,
                    "top_entity_name": "KESLEY MARTINS COSTA",
                    "top_entity_value": "260592604,18999854",
                    "is_top_entity": False,
                },
            }
        },
    )

    chat = ChatAnswerService(api_key=None, model="fallback").compose(
        request=UserRequest(message="verifica se THIAGO MORAES BARBOSA e o liner com mais proposta vgv"),
        orchestration=response,
    )

    assert "THIAGO MORAES BARBOSA nao e o liner com maior Propostas VGV." in chat.message
    assert "KESLEY MARTINS COSTA lidera com 260592604,18999854." in chat.message
    assert "Relatorio Power BI aberto: Top_Atual2." in chat.message
