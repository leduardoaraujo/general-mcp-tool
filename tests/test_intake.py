from mcp_orchestrator.application import HeuristicRequestInterpreter
from mcp_orchestrator.domain.enums import McpTarget, RequestedAction, RiskLevel, TaskType
from mcp_orchestrator.domain.models import OrchestrateRequest


def test_power_bi_request_selects_power_bi() -> None:
    interpreter = HeuristicRequestInterpreter()

    result = interpreter.interpret(
        OrchestrateRequest(message="Show Total Sales from the Power BI semantic model")
    )

    assert McpTarget.POWER_BI in result.candidate_mcps
    assert result.task_type == TaskType.SEMANTIC_MODEL_QUERY
    assert result.requested_action == RequestedAction.READ
    assert result.reasoning_summary


def test_power_bi_metadata_request_is_model_inspection() -> None:
    interpreter = HeuristicRequestInterpreter()

    result = interpreter.interpret(
        OrchestrateRequest(message="List Power BI semantic model tables and measures")
    )

    assert result.candidate_mcps == [McpTarget.POWER_BI]
    assert result.task_type == TaskType.SEMANTIC_MODEL_INSPECTION
    assert result.requested_action == RequestedAction.INSPECT_MODEL


def test_power_bi_dax_request_is_dax_query() -> None:
    interpreter = HeuristicRequestInterpreter()

    result = interpreter.interpret(
        OrchestrateRequest(message="Generate a DAX preview for Total Sales in Power BI")
    )

    assert result.candidate_mcps == [McpTarget.POWER_BI]
    assert result.task_type == TaskType.DAX_QUERY
    assert result.requested_action == RequestedAction.GENERATE_QUERY


def test_power_bi_refresh_request_is_high_risk() -> None:
    interpreter = HeuristicRequestInterpreter()

    result = interpreter.interpret(
        OrchestrateRequest(message="Refresh the Power BI semantic model")
    )

    assert result.candidate_mcps == [McpTarget.POWER_BI]
    assert result.requested_action == RequestedAction.REFRESH
    assert result.risk_level == RiskLevel.HIGH


def test_sql_request_selects_postgresql_by_default() -> None:
    interpreter = HeuristicRequestInterpreter()

    result = interpreter.interpret(
        OrchestrateRequest(message="Write a SQL query joining sales_orders and customers")
    )

    assert result.candidate_mcps == [McpTarget.POSTGRESQL]
    assert result.task_type == TaskType.SQL_QUERY
    assert result.target_preference == McpTarget.POSTGRESQL
    assert result.ambiguities == ["SQL dialect was not explicit; PostgreSQL is the Phase 1 default."]


def test_explicit_sql_server_request_selects_sql_server() -> None:
    interpreter = HeuristicRequestInterpreter()

    result = interpreter.interpret(
        OrchestrateRequest(message="Write a SQL Server query for sales_orders")
    )

    assert McpTarget.SQL_SERVER in result.candidate_mcps


def test_excel_request_selects_excel() -> None:
    interpreter = HeuristicRequestInterpreter()

    result = interpreter.interpret(
        OrchestrateRequest(message="Extract confirmed orders from an Excel worksheet")
    )

    assert result.candidate_mcps == [McpTarget.EXCEL]
    assert result.task_type == TaskType.TABULAR_EXTRACTION


def test_mixed_request_is_composite() -> None:
    interpreter = HeuristicRequestInterpreter()

    result = interpreter.interpret(
        OrchestrateRequest(message="Compare Power BI measures with a PostgreSQL SQL query")
    )

    assert result.task_type == TaskType.COMPOSITE
    assert len(result.candidate_mcps) > 1
    assert "Multiple specialist MCP targets may be relevant." in result.ambiguities


def test_write_request_is_high_risk() -> None:
    interpreter = HeuristicRequestInterpreter()

    result = interpreter.interpret(
        OrchestrateRequest(message="Delete rows from PostgreSQL sales_orders")
    )

    assert result.requested_action == RequestedAction.WRITE
    assert result.risk_level == RiskLevel.HIGH
