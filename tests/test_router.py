import pytest

from mcp_orchestrator.application import (
    DefaultContextComposer,
    ExecutionRouter,
    HeuristicRequestInterpreter,
    McpRouter,
)
from mcp_orchestrator.domain.enums import ExecutionMode, McpTarget
from mcp_orchestrator.domain.models import OrchestrateRequest, RagContext
from mcp_orchestrator.infrastructure.mcp_clients import DefaultMcpClientRegistry


def build_enriched(message: str):
    request = OrchestrateRequest(message=message)
    interpretation = HeuristicRequestInterpreter().interpret(request)
    return DefaultContextComposer().compose(
        "test-correlation",
        request,
        interpretation,
        RagContext(query=message, items=[], filters={}, total_candidates=0),
    )


def test_semantic_model_routes_to_power_bi() -> None:
    router = McpRouter(DefaultMcpClientRegistry())

    clients, trace = router.select_clients(
        build_enriched("Show Total Sales from the Power BI semantic model")
    )

    assert [client.name for client in clients] == ["power_bi"]
    assert trace


def test_excel_extraction_routes_to_excel() -> None:
    router = McpRouter(DefaultMcpClientRegistry())

    clients, _ = router.select_clients(build_enriched("Read this Excel worksheet"))

    assert [client.name for client in clients] == ["excel"]


def test_postgresql_request_builds_preview_execution_plan() -> None:
    router = ExecutionRouter(DefaultMcpClientRegistry())

    plan = router.create_plan(
        build_enriched("Use PostgreSQL to prepare monthly sales revenue SQL")
    )

    assert plan.target_mcps == [McpTarget.POSTGRESQL]
    assert plan.execution_mode == ExecutionMode.PREVIEW_ONLY
    assert plan.tool_hints[McpTarget.POSTGRESQL] == "run_guided_query"


def test_generic_sql_request_does_not_select_sql_server_in_phase_zero() -> None:
    router = ExecutionRouter(DefaultMcpClientRegistry())

    plan = router.create_plan(
        build_enriched("Write a SQL query joining sales_orders and customers")
    )

    assert plan.target_mcps == [McpTarget.POSTGRESQL]


@pytest.mark.asyncio
async def test_composite_request_executes_multiple_clients() -> None:
    router = McpRouter(DefaultMcpClientRegistry())
    enriched = build_enriched("Compare Power BI sales measures with a PostgreSQL query")
    clients, trace = router.select_clients(enriched)

    results = await router.execute_clients(enriched, clients, trace)

    assert len(results) > 1
    assert {result.mcp_name for result in results}.issuperset({"power_bi", "postgresql"})
