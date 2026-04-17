from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .enums import DocumentType, Domain, McpTarget, ResultStatus, TaskType


class OrchestrateRequest(BaseModel):
    message: str = Field(min_length=1)
    domain_hint: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RequestInterpretation(BaseModel):
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


class RagContext(BaseModel):
    query: str
    items: list[RetrievedContextItem] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    total_candidates: int = 0


class EnrichedRequest(BaseModel):
    correlation_id: str
    original_request: str
    interpretation: RequestInterpretation
    rag_context: RagContext
    execution_instructions: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    expected_response_format: str


class MCPResult(BaseModel):
    mcp_name: str
    status: ResultStatus
    summary: str
    raw_output: dict[str, Any] = Field(default_factory=dict)
    structured_data: dict[str, Any] | list[dict[str, Any]] | None = None
    sources_used: list[str] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    duration_ms: float = Field(ge=0.0)


class NormalizedResponse(BaseModel):
    correlation_id: str
    status: ResultStatus
    summary: str
    raw_outputs: list[MCPResult] = Field(default_factory=list)
    structured_data: dict[str, Any] | list[dict[str, Any]] | None = None
    sources_used: list[str] = Field(default_factory=list)
    mcp_trace: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    timings: dict[str, float] = Field(default_factory=dict)
