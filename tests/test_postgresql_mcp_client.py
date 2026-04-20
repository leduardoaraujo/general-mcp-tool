import pytest

from mcp_orchestrator.application import DefaultContextComposer, ExecutionRouter, HeuristicRequestInterpreter
from mcp_orchestrator.domain.enums import McpTarget, ResultStatus
from mcp_orchestrator.domain.models import McpToolCallResponse, RetrievedContext, UserRequest
from mcp_orchestrator.infrastructure.mcp_clients import DefaultMcpClientRegistry
from mcp_orchestrator.infrastructure.mcp_clients.postgresql import PostgreSqlMcpClient
from mcp_orchestrator.infrastructure.mcp_servers import McpServerDefinition


class FakeCatalog:
    def get(self, name: str) -> McpServerDefinition | None:
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


def build_postgres_specialist_request():
    user_request = UserRequest(
        message="Use PostgreSQL to prepare monthly sales revenue SQL.",
        domain_hint="postgresql",
        tags=["sales", "postgresql"],
    )
    understanding = HeuristicRequestInterpreter().understand(user_request)
    enriched = DefaultContextComposer().compose(
        "cid",
        user_request,
        understanding,
        RetrievedContext(query=user_request.message),
    )
    fake_client = PostgreSqlMcpClient(server_catalog=FakeCatalog(), tool_runner=FakeRunner())  # type: ignore[arg-type]
    router = ExecutionRouter(DefaultMcpClientRegistry(clients=[fake_client]))
    plan = router.create_plan(enriched)
    return router._specialist_request(  # noqa: SLF001
        enriched,
        plan,
        fake_client,
    )


def test_router_builds_postgresql_preview_request_from_enriched_context() -> None:
    specialist_request = build_postgres_specialist_request()

    assert specialist_request.tool_name == "run_guided_query"
    assert specialist_request.arguments["auto_execute"] is False
    assert specialist_request.arguments["limit"] == 100
    assert specialist_request.arguments["question"] != specialist_request.enriched_request.original_request
    assert "Original user request:" in str(specialist_request.arguments["question"])


@pytest.mark.asyncio
async def test_postgresql_client_calls_run_guided_query_preview() -> None:
    runner = FakeRunner()
    client = PostgreSqlMcpClient(server_catalog=FakeCatalog(), tool_runner=runner)  # type: ignore[arg-type]
    request = build_postgres_specialist_request()

    result = await client.execute(request)

    assert runner.calls[0][0] == "run_guided_query"
    assert runner.calls[0][1]["auto_execute"] is False
    assert result.status == ResultStatus.SUCCESS
    assert result.structured_data == {"sql": "select 1", "preview_only": True}
    assert result.debug["raw_result"] == {"transport": "stdio"}


@pytest.mark.asyncio
async def test_postgresql_client_maps_tool_errors() -> None:
    runner = FakeRunner(is_error=True)
    client = PostgreSqlMcpClient(server_catalog=FakeCatalog(), tool_runner=runner)  # type: ignore[arg-type]
    request = build_postgres_specialist_request()

    result = await client.execute(request)

    assert result.status == ResultStatus.ERROR
    assert result.errors == ["failed"]
