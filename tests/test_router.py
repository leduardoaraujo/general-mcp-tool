import pytest

from mcp_orchestrator.application import (
    DefaultContextComposer,
    DefaultExecutionPolicyService,
    ExecutionRouter,
    HeuristicRequestInterpreter,
    McpRouter,
)
from mcp_orchestrator.application.trace import OrchestrationTraceRecorder
from mcp_orchestrator.domain.enums import ExecutionMode, McpTarget, ResultStatus
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


def test_power_bi_request_builds_semantic_execution_plan() -> None:
    router = ExecutionRouter(DefaultMcpClientRegistry())
    enriched = build_enriched("List Power BI semantic model tables and measures")
    policy = DefaultExecutionPolicyService().decide(
        enriched,
        OrchestrationTraceRecorder("test-correlation").trace,
    )

    plan = router.create_plan(enriched, policy)

    assert plan.target_mcps == [McpTarget.POWER_BI]
    assert plan.execution_mode == ExecutionMode.SIMPLE
    assert plan.policy_decision is policy
    assert plan.policy_decision.allow_execution is True
    assert plan.tool_hints[McpTarget.POWER_BI] == "run_guided_modeling_request"


@pytest.mark.asyncio
async def test_power_bi_refresh_is_blocked_before_specialist_call() -> None:
    router = ExecutionRouter(DefaultMcpClientRegistry())
    enriched = build_enriched("Refresh the Power BI semantic model")
    policy = DefaultExecutionPolicyService().decide(
        enriched,
        OrchestrationTraceRecorder("test-correlation").trace,
    )
    plan = router.create_plan(enriched, policy)

    results = await router.execute_plan(enriched, plan)

    assert results[0].mcp_name == "execution_policy"
    assert results[0].status == ResultStatus.ERROR


def test_excel_extraction_routes_to_excel() -> None:
    router = McpRouter(DefaultMcpClientRegistry())

    clients, _ = router.select_clients(build_enriched("Read this Excel worksheet"))

    assert [client.name for client in clients] == ["excel"]


def test_postgresql_request_builds_preview_execution_plan() -> None:
    router = ExecutionRouter(DefaultMcpClientRegistry())
    enriched = build_enriched("Use PostgreSQL to prepare monthly sales revenue SQL")
    policy = DefaultExecutionPolicyService().decide(
        enriched,
        OrchestrationTraceRecorder("test-correlation").trace,
    )

    plan = router.create_plan(enriched, policy)

    assert plan.target_mcps == [McpTarget.POSTGRESQL]
    assert plan.execution_mode == ExecutionMode.PREVIEW_ONLY
    assert plan.policy_decision is policy
    assert plan.tool_hints[McpTarget.POSTGRESQL] == "run_guided_query"


def test_explicit_sql_server_request_builds_preview_execution_plan() -> None:
    router = ExecutionRouter(DefaultMcpClientRegistry())
    enriched = build_enriched("Use SQL Server to prepare monthly sales revenue SQL")
    policy = DefaultExecutionPolicyService().decide(
        enriched,
        OrchestrationTraceRecorder("test-correlation").trace,
    )

    plan = router.create_plan(enriched, policy)

    assert plan.target_mcps == [McpTarget.SQL_SERVER]
    assert plan.execution_mode == ExecutionMode.PREVIEW_ONLY
    assert plan.policy_decision is policy
    assert plan.tool_hints[McpTarget.SQL_SERVER] == "run_guided_query"


def test_explicit_mssql_request_routes_to_sql_server() -> None:
    router = ExecutionRouter(DefaultMcpClientRegistry())

    plan = router.create_plan(build_enriched("Use MSSQL to prepare revenue SQL"))

    assert plan.target_mcps == [McpTarget.SQL_SERVER]


def test_explicit_tsql_request_routes_to_sql_server() -> None:
    router = ExecutionRouter(DefaultMcpClientRegistry())

    plan = router.create_plan(build_enriched("Use T-SQL to inspect sales_orders"))

    assert plan.target_mcps == [McpTarget.SQL_SERVER]


def test_generic_sql_request_defaults_to_postgresql() -> None:
    router = ExecutionRouter(DefaultMcpClientRegistry())

    plan = router.create_plan(
        build_enriched("Write a SQL query joining sales_orders and customers")
    )

    assert plan.target_mcps == [McpTarget.POSTGRESQL]


def test_both_relational_clients_are_preview_first_by_default() -> None:
    router = ExecutionRouter(DefaultMcpClientRegistry())

    postgres_plan = router.create_plan(build_enriched("Use PostgreSQL to prepare revenue SQL"))
    sql_server_plan = router.create_plan(build_enriched("Use SQL Server to prepare revenue SQL"))

    assert postgres_plan.execution_mode == ExecutionMode.PREVIEW_ONLY
    assert sql_server_plan.execution_mode == ExecutionMode.PREVIEW_ONLY


@pytest.mark.asyncio
async def test_policy_blocked_plan_does_not_call_specialist() -> None:
    router = ExecutionRouter(DefaultMcpClientRegistry())
    enriched = build_enriched("Delete rows from PostgreSQL sales_orders")
    policy = DefaultExecutionPolicyService().decide(
        enriched,
        OrchestrationTraceRecorder("test-correlation").trace,
    )
    plan = router.create_plan(enriched, policy)

    results = await router.execute_plan(enriched, plan)

    assert results[0].mcp_name == "execution_policy"
    assert results[0].status == ResultStatus.ERROR


@pytest.mark.asyncio
async def test_composite_request_executes_multiple_clients() -> None:
    router = McpRouter(DefaultMcpClientRegistry())
    enriched = build_enriched("Compare Power BI sales measures with a PostgreSQL query")
    clients, trace = router.select_clients(enriched)

    results = await router.execute_clients(enriched, clients, trace)

    assert len(results) > 1
    assert {result.mcp_name for result in results}.issuperset({"power_bi", "postgresql"})
