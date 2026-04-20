from mcp_orchestrator.domain.enums import (
    ExecutionMode,
    McpTarget,
    RequestedAction,
    ResultStatus,
    RiskLevel,
    SafetyLevel,
    TaskType,
)
from mcp_orchestrator.domain.models import (
    EnrichedRequest,
    ExecutionPlan,
    ExecutionPolicyDecision,
    McpClientCapability,
    NormalizedResponse,
    OrchestrationTrace,
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
        requested_action=RequestedAction.GENERATE_QUERY,
        target_preference=McpTarget.POSTGRESQL,
        candidate_mcps=[McpTarget.POSTGRESQL],
        risk_level=RiskLevel.LOW,
        reasoning_summary="Rule-based interpretation.",
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
    policy = ExecutionPolicyDecision(
        correlation_id="cid",
        preview_only=True,
        read_only=False,
        write=False,
        side_effects=False,
        requires_confirmation=False,
        allow_execution=False,
        safety_level=SafetyLevel.SAFE,
        risk_level=RiskLevel.LOW,
        decision_reason="Preview-first default.",
    )
    plan = ExecutionPlan(
        correlation_id="cid",
        target_mcps=[McpTarget.POSTGRESQL],
        execution_mode=ExecutionMode.PREVIEW_ONLY,
        tool_hints={McpTarget.POSTGRESQL: "run_guided_query"},
        policy_decision=policy,
    )
    trace = OrchestrationTrace(request_id="cid", policy_decision=policy)
    capability = McpClientCapability(
        name="postgresql",
        target=McpTarget.POSTGRESQL,
        supports_preview=True,
        supports_read=True,
        metadata_read=True,
        default_tool="run_guided_query",
    )
    specialist_request = SpecialistExecutionRequest(
        correlation_id="cid",
        target=McpTarget.POSTGRESQL,
        tool_name="run_guided_query",
        arguments={"auto_execute": False},
        enriched_request=enriched,
        execution_plan=plan,
        policy_decision=policy,
        orchestration_trace=trace,
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
    assert enriched.model_dump()["understanding"]["requested_action"] == "generate_query"
    assert plan.model_dump()["policy_decision"]["preview_only"] is True
    assert capability.model_dump()["supports_read"] is True
    assert capability.model_dump()["metadata_read"] is True
    assert capability.model_dump()["semantic_model_inspection"] is False
    assert specialist_request.model_dump()["policy_decision"]["safety_level"] == "safe"
    assert specialist_request.model_dump()["tool_name"] == "run_guided_query"
    assert response.model_dump()["specialist_results"][0]["mcp_name"] == "postgresql"
    assert response.model_dump()["raw_outputs"][0]["mcp_name"] == "postgresql"
