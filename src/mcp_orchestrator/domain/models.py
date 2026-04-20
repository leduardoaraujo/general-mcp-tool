from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, computed_field

from .enums import (
    DocumentType,
    Domain,
    ExecutionMode,
    McpTarget,
    RequestedAction,
    ResultStatus,
    RiskLevel,
    SafetyLevel,
    TaskType,
)


class UserRequest(BaseModel):
    message: str = Field(min_length=1)
    domain_hint: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RequestUnderstanding(BaseModel):
    original_request: str
    intent: str
    domain: Domain
    task_type: TaskType
    requested_action: RequestedAction = RequestedAction.UNKNOWN
    target_preference: McpTarget | None = None
    relevant_sources: list[str] = Field(default_factory=list)
    candidate_mcps: list[McpTarget] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    ambiguities: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    risk_level: RiskLevel = RiskLevel.LOW
    reasoning_summary: str = ""


class RetrievedContextItem(BaseModel):
    source_path: str
    document_type: DocumentType
    domain: Domain | None = None
    tags: list[str] = Field(default_factory=list)
    content: str
    score: float = Field(ge=0.0)


class RetrievedContext(BaseModel):
    query: str
    items: list[RetrievedContextItem] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    total_candidates: int = 0


class EnrichedRequest(BaseModel):
    correlation_id: str
    original_request: str
    understanding: RequestUnderstanding
    retrieved_context: RetrievedContext
    execution_instructions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    expected_response_format: str

    @property
    def interpretation(self) -> RequestUnderstanding:
        return self.understanding

    @property
    def rag_context(self) -> RetrievedContext:
        return self.retrieved_context


class ExecutionPolicyDecision(BaseModel):
    correlation_id: str
    preview_only: bool
    read_only: bool
    write: bool
    side_effects: bool
    requires_confirmation: bool
    allow_execution: bool
    blocked_reason: str | None = None
    safety_level: SafetyLevel
    risk_level: RiskLevel
    decision_reason: str
    warnings: list[str] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)


class McpClientCapability(BaseModel):
    name: str
    target: McpTarget
    supports_preview: bool = True
    supports_read: bool = False
    supports_write: bool = False
    supports_side_effects: bool = False
    semantic_model_inspection: bool = False
    table_listing: bool = False
    measure_listing: bool = False
    dax_support: bool = False
    metadata_read: bool = False
    refresh_support: bool = False
    model_write_support: bool = False
    side_effect_support: bool = False
    default_tool: str | None = None
    supported_tools: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class OrchestrationTraceStage(BaseModel):
    name: str
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: float | None = Field(default=None, ge=0.0)
    status: str = "started"
    details: dict[str, Any] = Field(default_factory=dict)


class OrchestrationTrace(BaseModel):
    request_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    stages: list[OrchestrationTraceStage] = Field(default_factory=list)
    selected_target_mcps: list[McpTarget] = Field(default_factory=list)
    retrieved_context_sources: list[str] = Field(default_factory=list)
    policy_decision: ExecutionPolicyDecision | None = None
    warnings: list[str] = Field(default_factory=list)
    fallback_information: list[str] = Field(default_factory=list)
    debug_notes: list[str] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    correlation_id: str
    target_mcps: list[McpTarget] = Field(default_factory=list)
    execution_mode: ExecutionMode
    tool_hints: dict[McpTarget, str] = Field(default_factory=dict)
    policy_decision: ExecutionPolicyDecision | None = None
    trace: list[str] = Field(default_factory=list)


class SpecialistExecutionRequest(BaseModel):
    correlation_id: str
    target: McpTarget
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    enriched_request: EnrichedRequest
    execution_plan: ExecutionPlan
    policy_decision: ExecutionPolicyDecision | None = None
    orchestration_trace: OrchestrationTrace | None = None


class SpecialistExecutionResult(BaseModel):
    mcp_name: str
    target: McpTarget | None = None
    status: ResultStatus
    summary: str
    structured_data: dict[str, Any] | list[dict[str, Any]] | None = None
    sources_used: list[str] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    duration_ms: float = Field(ge=0.0)
    debug: dict[str, Any] = Field(default_factory=dict)


class NormalizedResponse(BaseModel):
    correlation_id: str
    status: ResultStatus
    summary: str
    specialist_results: list[SpecialistExecutionResult] = Field(default_factory=list)
    structured_data: dict[str, Any] | list[dict[str, Any]] | None = None
    sources_used: list[str] = Field(default_factory=list)
    mcp_trace: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    timings: dict[str, float] = Field(default_factory=dict)
    debug: dict[str, Any] = Field(default_factory=dict)

    @computed_field
    @property
    def raw_outputs(self) -> list[SpecialistExecutionResult]:
        return self.specialist_results


class McpToolDefinition(BaseModel):
    name: str
    description: str | None = None
    input_schema: dict[str, Any] = Field(default_factory=dict)


class McpToolCallRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


class McpToolCallResponse(BaseModel):
    server_name: str
    tool_name: str
    is_error: bool
    content: list[str] = Field(default_factory=list)
    structured_content: dict[str, Any] | list[Any] | None = None
    raw_result: dict[str, Any] = Field(default_factory=dict)


# Compatibility names kept during the Phase 0 migration.
OrchestrateRequest = UserRequest
RequestInterpretation = RequestUnderstanding
RagContext = RetrievedContext
MCPResult = SpecialistExecutionResult
