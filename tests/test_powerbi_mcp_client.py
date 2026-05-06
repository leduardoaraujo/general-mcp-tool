import json

import pytest

from mcp_orchestrator.application import (
    DefaultContextComposer,
    DefaultExecutionPolicyService,
    ExecutionRouter,
    HeuristicRequestInterpreter,
)
from mcp_orchestrator.application.trace import OrchestrationTraceRecorder
from mcp_orchestrator.domain.enums import McpTarget, ResultStatus
from mcp_orchestrator.domain.models import McpToolCallResponse, RetrievedContext, UserRequest
from mcp_orchestrator.infrastructure.mcp_clients import DefaultMcpClientRegistry
from mcp_orchestrator.infrastructure.mcp_clients.powerbi import PowerBiMcpClient
from mcp_orchestrator.infrastructure.mcp_servers import McpServerDefinition


class FakeCatalog:
    def __init__(self, *, has_server: bool = True) -> None:
        self.has_server = has_server

    def get(self, name: str) -> McpServerDefinition | None:
        if not self.has_server:
            return None
        return McpServerDefinition(
            name=name,
            kind="npm",
            path=".",
            command="powerbi-modeling-mcp",
            args=["--start"],
            has_pyproject=False,
            has_requirements=False,
            package_name="@microsoft/powerbi-modeling-mcp",
            package_version="0.5.0-beta.3",
        )


class FakeRunner:
    def __init__(self, *, is_error: bool = False) -> None:
        self.is_error = is_error
        self.calls: list[tuple[str, dict[str, object]]] = []

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
            is_error=self.is_error,
            content=["model metadata" if not self.is_error else "failed"],
            structured_content={
                "tables": ["Sales"],
                "measures": ["Total Sales"],
                "preview_only": True,
            }
            if not self.is_error
            else {"code": "failed"},
            raw_result={"transport": "stdio"},
        )


class FakeSessionCaller:
    def __init__(self, calls: list[tuple[str, dict[str, object]]]) -> None:
        self.calls = calls

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, object],
    ) -> McpToolCallResponse:
        self.calls.append((tool_name, arguments))
        request = arguments["request"]  # type: ignore[index]
        operation = request["operation"]  # type: ignore[index]

        payloads = {
            ("connection_operations", "ListLocalInstances"): {
                "success": True,
                "operation": "ListLocalInstances",
                "data": [
                    {
                        "connectionString": "Data Source=localhost:58211",
                        "parentWindowTitle": "Planejamentov12",
                    }
                ],
            },
            ("connection_operations", "Connect"): {
                "success": True,
                "operation": "Connect",
                "data": "PBIDesktop-Planejamentov12-58211",
            },
            ("measure_operations", "List"): {
                "success": True,
                "operation": "List",
                "data": [
                    {"name": "Custo Unitário Prato"},
                    {"name": "Custo Unitário do Prato (KPI)"},
                    {"name": "Total Custo"},
                    {"name": "Propostas VGV"},
                    {"name": "Propostas VGV Filtro 2"},
                    {"name": "VGV Vendido"},
                    {"name": "Mega Meta VGV"},
                ],
            },
            ("measure_operations", "Get"): {
                "success": True,
                "operation": "Get",
                "results": [
                    {
                        "success": True,
                        "data": {
                            "tableName": "Medidas",
                            "name": "Custo Unitário Prato",
                            "expression": "DIVIDE([Custo Realizado], [Porções Prato])",
                        },
                    }
                ],
            },
        }
        if tool_name == "dax_query_operations" and operation == "Execute":
            csv_text = (
                "EntityType,EntityName,MeasureName,MetricValue,MetricRank,TopEntityName,TopMetricValue,IsTopEntity\r\n"
                "liner,THIAGO MORAES BARBOSA,Propostas VGV,\"22720675,050000004\",160,"
                "KESLEY MARTINS COSTA,\"260592604,18999854\",False\r\n"
            )
            return McpToolCallResponse(
                server_name="power_bi",
                tool_name=tool_name,
                is_error=False,
                content=['{"success":true}'],
                structured_content=None,
                raw_result={
                    "content": [
                        {"type": "text", "text": '{"success":true}'},
                        {
                            "type": "resource",
                            "resource": {"mimeType": "text/csv", "text": csv_text},
                        },
                    ]
                },
            )

        payload = payloads[(tool_name, operation)]
        return McpToolCallResponse(
            server_name="power_bi",
            tool_name=tool_name,
            is_error=False,
            content=[json.dumps(payload)],
            structured_content=None,
            raw_result={"payload": payload},
        )


class FakeSessionRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def call_with_session(self, server, callback):  # noqa: ANN001
        return await callback(FakeSessionCaller(self.calls))

    async def call_tool(
        self,
        server: McpServerDefinition,
        tool_name: str,
        arguments: dict[str, object],
    ) -> McpToolCallResponse:
        raise AssertionError("guided Power BI execution should use one stdio session")


def build_power_bi_specialist_request(
    *,
    message: str = "List Power BI semantic model tables and measures.",
    allow_execution: bool = False,
):
    user_request = UserRequest(
        message=message,
        domain_hint="power bi",
        tags=["sales", "power_bi"],
        metadata={"allow_execution": allow_execution} if allow_execution else {},
    )
    understanding = HeuristicRequestInterpreter().understand(user_request)
    enriched = DefaultContextComposer().compose(
        "cid",
        user_request,
        understanding,
        RetrievedContext(query=user_request.message),
    )
    fake_client = PowerBiMcpClient(
        server_catalog=FakeCatalog(),
        tool_runner=FakeRunner(),
    )  # type: ignore[arg-type]
    router = ExecutionRouter(DefaultMcpClientRegistry(clients=[fake_client]))
    trace = OrchestrationTraceRecorder("cid").trace
    policy = DefaultExecutionPolicyService().decide(enriched, trace)
    plan = router.create_plan(enriched, policy)
    return router._specialist_request(  # noqa: SLF001
        enriched,
        plan,
        fake_client,
        trace,
    )


def test_power_bi_capabilities_describe_semantic_support() -> None:
    client = PowerBiMcpClient(
        server_catalog=FakeCatalog(),
        tool_runner=FakeRunner(),
    )  # type: ignore[arg-type]

    capabilities = client.capabilities()

    assert capabilities.target == McpTarget.POWER_BI
    assert capabilities.semantic_model_inspection is True
    assert capabilities.measure_listing is True
    assert capabilities.table_listing is True
    assert capabilities.dax_support is True
    assert capabilities.metadata_read is True
    assert capabilities.refresh_support is False
    assert capabilities.model_write_support is False
    assert capabilities.default_tool == "run_guided_modeling_request"


def test_router_builds_power_bi_semantic_read_request() -> None:
    specialist_request = build_power_bi_specialist_request()

    assert specialist_request.target == McpTarget.POWER_BI
    assert specialist_request.tool_name == "run_guided_modeling_request"
    assert specialist_request.arguments["preview_only"] is False
    assert specialist_request.arguments["allow_write"] is False
    assert "Power BI semantic-model response" in str(specialist_request.arguments["request"])
    assert specialist_request.policy_decision is not None
    assert specialist_request.policy_decision.allow_execution is True


def test_router_builds_power_bi_dax_preview_request() -> None:
    specialist_request = build_power_bi_specialist_request(
        message="Generate a DAX preview for Total Sales in the Power BI semantic model.",
    )

    assert specialist_request.tool_name == "run_guided_modeling_request"
    assert specialist_request.arguments["preview_only"] is True
    assert "dax_query" in str(specialist_request.arguments["request"])


@pytest.mark.asyncio
async def test_power_bi_client_calls_guided_modeling_request() -> None:
    runner = FakeRunner()
    client = PowerBiMcpClient(
        server_catalog=FakeCatalog(),
        tool_runner=runner,
    )  # type: ignore[arg-type]
    request = build_power_bi_specialist_request()

    result = await client.execute(request)

    assert runner.calls[0][0] == "run_guided_modeling_request"
    assert result.status == ResultStatus.SUCCESS
    assert result.structured_data == {
        "tables": ["Sales"],
        "measures": ["Total Sales"],
        "preview_only": True,
    }
    assert result.debug["raw_result"] == {"transport": "stdio"}


@pytest.mark.asyncio
async def test_power_bi_client_guided_request_uses_real_power_bi_tools_in_one_session() -> None:
    runner = FakeSessionRunner()
    client = PowerBiMcpClient(
        server_catalog=FakeCatalog(),
        tool_runner=runner,
    )  # type: ignore[arg-type]
    request = build_power_bi_specialist_request(
        message="qual a medida que mostra o custo unitario por prato?",
    )

    result = await client.execute(request)

    assert result.status == ResultStatus.SUCCESS
    assert [call[0] for call in runner.calls] == [
        "connection_operations",
        "connection_operations",
        "measure_operations",
        "measure_operations",
    ]
    assert "Custo Unitário Prato" in result.summary
    assert "DIVIDE([Custo Realizado], [Porções Prato])" in result.summary
    assert result.structured_data["connection"]["parentWindowTitle"] == "Planejamentov12"
    assert result.structured_data["measure_definitions"][0]["name"] == "Custo Unitário Prato"


@pytest.mark.asyncio
async def test_power_bi_client_executes_ranking_validation_query() -> None:
    runner = FakeSessionRunner()
    client = PowerBiMcpClient(
        server_catalog=FakeCatalog(),
        tool_runner=runner,
    )  # type: ignore[arg-type]
    request = build_power_bi_specialist_request(
        message="verifica pra mim se o THIAGO MORAES BARBOSA e o liner com mais proposta vgv por favor",
    )

    result = await client.execute(request)

    assert result.status == ResultStatus.SUCCESS
    assert [call[0] for call in runner.calls] == [
        "connection_operations",
        "connection_operations",
        "measure_operations",
        "dax_query_operations",
    ]
    assert "THIAGO MORAES BARBOSA is not the top liner" in result.summary
    assert result.structured_data["ranking_analysis"]["entity_name"] == "THIAGO MORAES BARBOSA"
    assert result.structured_data["ranking_analysis"]["top_entity_name"] == "KESLEY MARTINS COSTA"
    assert result.structured_data["ranking_analysis"]["entity_rank"] == 160


@pytest.mark.asyncio
async def test_power_bi_client_executes_measure_value_query_by_text_intent() -> None:
    runner = FakeSessionRunner()
    client = PowerBiMcpClient(
        server_catalog=FakeCatalog(),
        tool_runner=runner,
    )  # type: ignore[arg-type]
    request = build_power_bi_specialist_request(
        message="qual o numero que Mega Meta VGV retorna?",
    )

    result = await client.execute(request)

    assert result.status == ResultStatus.SUCCESS
    assert [call[0] for call in runner.calls] == [
        "connection_operations",
        "connection_operations",
        "measure_operations",
        "dax_query_operations",
    ]
    assert "dax_query_results" in result.structured_data
    assert result.structured_data["dax_query_results"]["value"] is not None


@pytest.mark.asyncio
async def test_power_bi_client_executes_comparison_query_for_meta_requests() -> None:
    runner = FakeSessionRunner()
    client = PowerBiMcpClient(
        server_catalog=FakeCatalog(),
        tool_runner=runner,
    )  # type: ignore[arg-type]
    request = build_power_bi_specialist_request(
        message="compara com o Mega Meta VGV",
    )

    result = await client.execute(request)

    assert result.status == ResultStatus.SUCCESS
    assert [call[0] for call in runner.calls] == [
        "connection_operations",
        "connection_operations",
        "measure_operations",
        "dax_query_operations",
    ]
    assert "dax_query_results" in result.structured_data
    assert result.structured_data["intent_detected"] == "comparacao"
    query = result.structured_data["dax_query_results"]["query"]
    assert "ComparisonValue" in query
    assert "[Mega Meta VGV]" in query


@pytest.mark.asyncio
async def test_power_bi_client_maps_tool_errors() -> None:
    runner = FakeRunner(is_error=True)
    client = PowerBiMcpClient(
        server_catalog=FakeCatalog(),
        tool_runner=runner,
    )  # type: ignore[arg-type]
    request = build_power_bi_specialist_request()

    result = await client.execute(request)

    assert result.status == ResultStatus.ERROR
    assert result.errors == ["failed"]


@pytest.mark.asyncio
async def test_power_bi_client_returns_controlled_error_when_server_is_missing() -> None:
    client = PowerBiMcpClient(
        server_catalog=FakeCatalog(has_server=False),
        tool_runner=FakeRunner(),
    )  # type: ignore[arg-type]
    request = build_power_bi_specialist_request()

    result = await client.execute(request)

    assert result.status == ResultStatus.ERROR
    assert result.summary == "Power BI MCP server was not found in the local catalog."
    assert result.errors == ["MCP server not found: power_bi"]
