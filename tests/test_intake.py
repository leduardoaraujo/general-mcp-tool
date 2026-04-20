from mcp_orchestrator.application import HeuristicRequestInterpreter
from mcp_orchestrator.domain.enums import McpTarget, TaskType
from mcp_orchestrator.domain.models import OrchestrateRequest


def test_power_bi_request_selects_power_bi() -> None:
    interpreter = HeuristicRequestInterpreter()

    result = interpreter.interpret(
        OrchestrateRequest(message="Show Total Sales from the Power BI semantic model")
    )

    assert McpTarget.POWER_BI in result.candidate_mcps
    assert result.task_type == TaskType.SEMANTIC_MODEL_QUERY


def test_sql_request_selects_postgresql_by_default() -> None:
    interpreter = HeuristicRequestInterpreter()

    result = interpreter.interpret(
        OrchestrateRequest(message="Write a SQL query joining sales_orders and customers")
    )

    assert result.candidate_mcps == [McpTarget.POSTGRESQL]
    assert result.task_type == TaskType.SQL_QUERY


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
