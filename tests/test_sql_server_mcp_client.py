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
from mcp_orchestrator.infrastructure.mcp_clients.sql_server import SqlServerMcpClient
from mcp_orchestrator.infrastructure.mcp_servers import McpServerDefinition


class FakeCatalog:
    def __init__(self, *, has_server: bool = True) -> None:
        self.has_server = has_server

    def get(self, name: str) -> McpServerDefinition | None:
        if not self.has_server:
            return None
        return McpServerDefinition(
            name=name,
            kind="python",
            path=".",
            command="python",
            args=["server.py"],
            has_pyproject=True,
            has_requirements=True,
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
            content=["preview" if not self.is_error else "failed"],
            structured_content={"sql": "select 1", "preview_only": True}
            if not self.is_error
            else {"code": "failed"},
            raw_result={"transport": "stdio"},
        )


def build_sql_server_specialist_request(
    *,
    allow_execution: bool = False,
    confirmation_id: str | None = None,
    message: str = "Use SQL Server to prepare monthly sales revenue SQL.",
):
    metadata = {"allow_execution": allow_execution} if allow_execution else {}
    if confirmation_id:
        metadata["confirmation_id"] = confirmation_id
    user_request = UserRequest(
        message=message,
        domain_hint="sql server",
        tags=["sales", "sql_server"],
        metadata=metadata,
    )
    understanding = HeuristicRequestInterpreter().understand(user_request)
    enriched = DefaultContextComposer().compose(
        "cid",
        user_request,
        understanding,
        RetrievedContext(query=user_request.message),
    )
    fake_client = SqlServerMcpClient(
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


def test_sql_server_capabilities_describe_preview_and_read_support() -> None:
    client = SqlServerMcpClient(
        server_catalog=FakeCatalog(),
        tool_runner=FakeRunner(),
    )  # type: ignore[arg-type]

    capabilities = client.capabilities()

    assert capabilities.target == McpTarget.SQL_SERVER
    assert capabilities.supports_preview is True
    assert capabilities.supports_read is True
    assert capabilities.supports_write is False
    assert capabilities.default_tool == "run_guided_query"


def test_router_builds_sql_server_preview_request_from_enriched_context() -> None:
    specialist_request = build_sql_server_specialist_request()

    assert specialist_request.target == McpTarget.SQL_SERVER
    assert specialist_request.tool_name == "run_guided_query"
    assert specialist_request.arguments["auto_execute"] is False
    assert specialist_request.arguments["limit"] == 100
    assert "SQL Server SQL preview" in str(specialist_request.arguments["question"])
    assert specialist_request.policy_decision is not None
    assert specialist_request.policy_decision.preview_only is True


def test_router_allows_sql_server_auto_execute_only_when_policy_allows() -> None:
    preview_request = build_sql_server_specialist_request(allow_execution=True)
    read_request = build_sql_server_specialist_request(
        allow_execution=True,
        confirmation_id="confirmation-1",
        message="Read rows from SQL Server sales_orders.",
    )

    assert preview_request.arguments["auto_execute"] is False
    assert read_request.arguments["auto_execute"] is True


@pytest.mark.asyncio
async def test_sql_server_client_calls_run_guided_query_preview() -> None:
    runner = FakeRunner()
    client = SqlServerMcpClient(
        server_catalog=FakeCatalog(),
        tool_runner=runner,
    )  # type: ignore[arg-type]
    request = build_sql_server_specialist_request()

    result = await client.execute(request)

    assert runner.calls[0][0] == "run_guided_query"
    assert runner.calls[0][1]["auto_execute"] is False
    assert result.status == ResultStatus.SUCCESS
    assert result.structured_data == {"sql": "select 1", "preview_only": True}
    assert result.debug["raw_result"] == {"transport": "stdio"}


@pytest.mark.asyncio
async def test_sql_server_client_maps_tool_errors() -> None:
    runner = FakeRunner(is_error=True)
    client = SqlServerMcpClient(
        server_catalog=FakeCatalog(),
        tool_runner=runner,
    )  # type: ignore[arg-type]
    request = build_sql_server_specialist_request()

    result = await client.execute(request)

    assert result.status == ResultStatus.ERROR
    assert result.errors == ["failed"]


@pytest.mark.asyncio
async def test_sql_server_client_returns_controlled_error_when_server_is_missing() -> None:
    client = SqlServerMcpClient(
        server_catalog=FakeCatalog(has_server=False),
        tool_runner=FakeRunner(),
    )  # type: ignore[arg-type]
    request = build_sql_server_specialist_request()

    result = await client.execute(request)

    assert result.status == ResultStatus.ERROR
    assert result.summary == "SQL Server MCP server was not found in the local catalog."
    assert result.errors == ["MCP server not found: sql_server"]
