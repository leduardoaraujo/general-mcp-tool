from mcp_orchestrator.application import (
    DefaultContextComposer,
    DefaultExecutionPolicyService,
    HeuristicRequestInterpreter,
)
from mcp_orchestrator.application.trace import OrchestrationTraceRecorder
from mcp_orchestrator.domain.enums import SafetyLevel
from mcp_orchestrator.domain.models import RetrievedContext, UserRequest


def build_enriched(
    message: str,
    metadata: dict[str, object] | None = None,
    *,
    domain_hint: str = "postgresql",
):
    request = UserRequest(message=message, domain_hint=domain_hint, metadata=metadata or {})
    understanding = HeuristicRequestInterpreter().understand(request)
    return DefaultContextComposer().compose(
        "cid",
        request,
        understanding,
        RetrievedContext(query=message),
    )


def test_policy_defaults_postgresql_to_preview_only() -> None:
    enriched = build_enriched("Use PostgreSQL to prepare monthly sales revenue SQL.")
    trace = OrchestrationTraceRecorder("cid").trace

    decision = DefaultExecutionPolicyService().decide(enriched, trace)

    assert decision.preview_only is True
    assert decision.allow_execution is False
    assert decision.safety_level == SafetyLevel.SAFE


def test_policy_requires_confirmation_for_explicit_read_only_execution() -> None:
    enriched = build_enriched(
        "Read rows from PostgreSQL sales_orders.",
        metadata={"allow_execution": True},
    )
    trace = OrchestrationTraceRecorder("cid").trace

    decision = DefaultExecutionPolicyService().decide(enriched, trace)

    assert decision.allow_execution is False
    assert decision.requires_confirmation is True
    assert decision.safety_level == SafetyLevel.BLOCKED
    assert "confirmation_id" in decision.blocked_reason


def test_policy_allows_explicit_read_only_execution_with_confirmation() -> None:
    enriched = build_enriched(
        "Read rows from PostgreSQL sales_orders.",
        metadata={"allow_execution": True, "confirmation_id": "confirmation-1"},
    )
    trace = OrchestrationTraceRecorder("cid").trace

    decision = DefaultExecutionPolicyService().decide(enriched, trace)

    assert decision.preview_only is False
    assert decision.read_only is True
    assert decision.allow_execution is True
    assert decision.confirmation_id == "confirmation-1"
    assert decision.safety_level == SafetyLevel.REVIEW_REQUIRED


def test_policy_creates_confirmation_id_for_read_only_preview() -> None:
    enriched = build_enriched("Read rows from PostgreSQL sales_orders.")
    trace = OrchestrationTraceRecorder("cid").trace

    decision = DefaultExecutionPolicyService().decide(enriched, trace)

    assert decision.preview_only is True
    assert decision.allow_execution is False
    assert decision.confirmation_id


def test_policy_blocks_write_requests() -> None:
    enriched = build_enriched("Delete rows from PostgreSQL sales_orders.")
    trace = OrchestrationTraceRecorder("cid").trace

    decision = DefaultExecutionPolicyService().decide(enriched, trace)

    assert decision.write is True
    assert decision.requires_confirmation is True
    assert decision.allow_execution is False
    assert decision.safety_level == SafetyLevel.BLOCKED
    assert decision.blocked_reason


def test_policy_auto_allows_safe_power_bi_read_execution() -> None:
    enriched = build_enriched(
        "verifica se THIAGO MORAES BARBOSA e o liner com mais proposta vgv",
        domain_hint="power_bi",
    )
    trace = OrchestrationTraceRecorder("cid").trace

    decision = DefaultExecutionPolicyService().decide(enriched, trace)

    assert decision.preview_only is False
    assert decision.read_only is True
    assert decision.allow_execution is True
    assert decision.safety_level == SafetyLevel.SAFE
    assert decision.confirmation_id is None
