from __future__ import annotations

from mcp_orchestrator.domain.enums import RequestedAction, RiskLevel, SafetyLevel
from mcp_orchestrator.domain.models import (
    EnrichedRequest,
    ExecutionPolicyDecision,
    OrchestrationTrace,
)


class DefaultExecutionPolicyService:
    def decide(
        self,
        enriched_request: EnrichedRequest,
        trace: OrchestrationTrace,
    ) -> ExecutionPolicyDecision:
        allow_execution_requested = bool(enriched_request.metadata.get("allow_execution", False))
        action = enriched_request.understanding.requested_action
        write = action == RequestedAction.WRITE
        side_effects = self._has_side_effects(enriched_request)
        read_only = action in {
            RequestedAction.READ,
            RequestedAction.INSPECT_SCHEMA,
            RequestedAction.INSPECT_MODEL,
        }

        if write or side_effects or action == RequestedAction.REFRESH:
            return self._blocked_decision(enriched_request, write=write, side_effects=side_effects)

        if read_only and allow_execution_requested:
            return self._read_execution_decision(enriched_request)

        return self._preview_decision(enriched_request, read_only=read_only)

    def _preview_decision(
        self,
        enriched_request: EnrichedRequest,
        *,
        read_only: bool,
    ) -> ExecutionPolicyDecision:
        warnings = []
        if read_only:
            warnings.append("Read execution was not explicitly allowed; using preview-only mode.")

        return ExecutionPolicyDecision(
            correlation_id=enriched_request.correlation_id,
            preview_only=True,
            read_only=read_only,
            write=False,
            side_effects=False,
            requires_confirmation=False,
            allow_execution=False,
            blocked_reason=None,
            safety_level=SafetyLevel.SAFE,
            risk_level=enriched_request.understanding.risk_level,
            decision_reason="Preview-only execution is the default policy.",
            warnings=warnings,
            trace=["Execution policy selected preview-only mode."],
        )

    def _read_execution_decision(self, enriched_request: EnrichedRequest) -> ExecutionPolicyDecision:
        return ExecutionPolicyDecision(
            correlation_id=enriched_request.correlation_id,
            preview_only=False,
            read_only=True,
            write=False,
            side_effects=False,
            requires_confirmation=False,
            allow_execution=True,
            blocked_reason=None,
            safety_level=SafetyLevel.REVIEW_REQUIRED,
            risk_level=RiskLevel.MEDIUM,
            decision_reason="Request metadata explicitly allowed read-only execution.",
            warnings=["Read-only execution was explicitly allowed by request metadata."],
            trace=["Execution policy allowed read-only execution."],
        )

    def _blocked_decision(
        self,
        enriched_request: EnrichedRequest,
        *,
        write: bool,
        side_effects: bool,
    ) -> ExecutionPolicyDecision:
        reason = "Write or side-effecting operations require a future confirmation workflow."
        return ExecutionPolicyDecision(
            correlation_id=enriched_request.correlation_id,
            preview_only=False,
            read_only=False,
            write=write,
            side_effects=side_effects,
            requires_confirmation=True,
            allow_execution=False,
            blocked_reason=reason,
            safety_level=SafetyLevel.BLOCKED,
            risk_level=RiskLevel.HIGH,
            decision_reason=reason,
            warnings=[reason],
            trace=["Execution policy blocked the request."],
        )

    def _has_side_effects(self, enriched_request: EnrichedRequest) -> bool:
        text = enriched_request.original_request.lower()
        side_effect_terms = ("send", "email", "publish", "refresh", "deploy")
        return any(term in text for term in side_effect_terms)
