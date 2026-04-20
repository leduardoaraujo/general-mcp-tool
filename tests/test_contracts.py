from mcp_orchestrator.domain.enums import ExecutionMode, McpTarget, ResultStatus, TaskType
from mcp_orchestrator.domain.models import (
    EnrichedRequest,
    ExecutionPlan,
    NormalizedResponse,
    RequestUnderstanding,
    RetrievedContext,
    SpecialistExecutionRequest,
    SpecialistExecutionResult,
    UserRequest,
)


def test_phase_zero_contracts_serialize_stable_fields() -> None:
    user_request = UserRequest(message="Prepare PostgreSQL SQL", domain_hint="postgresql")
    understanding = RequestUnderstanding(
        original_request=user_request.message,
        intent="Handle sql_query for postgresql.",
        domain="postgresql",
        task_type=TaskType.SQL_QUERY,
        candidate_mcps=[McpTarget.POSTGRESQL],
        confidence=0.8,
    )
    context = RetrievedContext(query=user_request.message)
    enriched = EnrichedRequest(
        correlation_id="cid",
        original_request=user_request.message,
        understanding=understanding,
        retrieved_context=context,
        expected_response_format="NormalizedResponse",
    )
    plan = ExecutionPlan(
        correlation_id="cid",
        target_mcps=[McpTarget.POSTGRESQL],
        execution_mode=ExecutionMode.PREVIEW_ONLY,
        tool_hints={McpTarget.POSTGRESQL: "run_guided_query"},
    )
    specialist_request = SpecialistExecutionRequest(
        correlation_id="cid",
        target=McpTarget.POSTGRESQL,
        tool_name="run_guided_query",
        arguments={"auto_execute": False},
        enriched_request=enriched,
        execution_plan=plan,
    )
    result = SpecialistExecutionResult(
        mcp_name="postgresql",
        target=McpTarget.POSTGRESQL,
        status=ResultStatus.SUCCESS,
        summary="ok",
        duration_ms=1,
    )
    response = NormalizedResponse(
        correlation_id="cid",
        status=ResultStatus.SUCCESS,
        summary="ok",
        specialist_results=[result],
    )

    assert user_request.model_dump()["message"] == "Prepare PostgreSQL SQL"
    assert enriched.model_dump()["understanding"]["task_type"] == "sql_query"
    assert specialist_request.model_dump()["tool_name"] == "run_guided_query"
    assert response.model_dump()["specialist_results"][0]["mcp_name"] == "postgresql"
    assert response.model_dump()["raw_outputs"][0]["mcp_name"] == "postgresql"
