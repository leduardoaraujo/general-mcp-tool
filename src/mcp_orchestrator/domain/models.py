from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, computed_field

from .enums import DocumentType, Domain, ExecutionMode, McpTarget, ResultStatus, TaskType


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
    relevant_sources: list[str] = Field(default_factory=list)
    candidate_mcps: list[McpTarget] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


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
    expected_response_format: str

    @property
    def interpretation(self) -> RequestUnderstanding:
        return self.understanding

    @property
    def rag_context(self) -> RetrievedContext:
        return self.retrieved_context


class ExecutionPlan(BaseModel):
    correlation_id: str
    target_mcps: list[McpTarget] = Field(default_factory=list)
    execution_mode: ExecutionMode
    tool_hints: dict[McpTarget, str] = Field(default_factory=dict)
    trace: list[str] = Field(default_factory=list)


class SpecialistExecutionRequest(BaseModel):
    correlation_id: str
    target: McpTarget
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    enriched_request: EnrichedRequest
    execution_plan: ExecutionPlan


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
