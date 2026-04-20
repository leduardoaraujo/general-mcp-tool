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


def test_router_builds_power_bi_semantic_preview_request() -> None:
    specialist_request = build_power_bi_specialist_request()

    assert specialist_request.target == McpTarget.POWER_BI
    assert specialist_request.tool_name == "run_guided_modeling_request"
    assert specialist_request.arguments["preview_only"] is True
    assert specialist_request.arguments["allow_write"] is False
    assert "Power BI semantic-model response" in str(specialist_request.arguments["request"])
    assert specialist_request.policy_decision is not None
    assert specialist_request.policy_decision.preview_only is True


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
