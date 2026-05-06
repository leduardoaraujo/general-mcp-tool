from __future__ import annotations

from uuid import uuid4

from mcp_orchestrator.config import Settings
from mcp_orchestrator.domain.models import (
    ChatRequest,
    ChatResponse,
    ConfirmationExecutionResponse,
    McpToolCallResponse,
    McpToolDefinition,
    NormalizedResponse,
    UserRequest,
)
from mcp_orchestrator.domain.ports import (
    ContextComposer,
    ContextRetriever,
    ExecutionPolicyService,
    RequestUnderstandingService,
    ResponseNormalizer,
)
from mcp_orchestrator.infrastructure.context import LocalContextRetriever
from mcp_orchestrator.infrastructure.audit import SqliteAuditStore
from mcp_orchestrator.infrastructure.mcp_clients import DefaultMcpClientRegistry
from mcp_orchestrator.infrastructure.mcp_servers import LocalMcpServerCatalog, StdioMcpToolRunner
from mcp_orchestrator.normalization import DefaultResponseNormalizer
from mcp_orchestrator.observability import TimingRecorder, get_logger, log_stage

from .composer import DefaultContextComposer
from .chat import ChatAnswerService
from .intake import HeuristicRequestUnderstandingService, OpenAIRequestUnderstandingService
from .policy import DefaultExecutionPolicyService
from .routing import ExecutionRouter
from .trace import OrchestrationTraceRecorder


class OrchestrationService:
    def __init__(
        self,
        *,
        understanding_service: RequestUnderstandingService | None = None,
        interpreter: RequestUnderstandingService | None = None,
        retriever: ContextRetriever,
        composer: ContextComposer,
        policy_service: ExecutionPolicyService | None = None,
        router: ExecutionRouter,
        normalizer: ResponseNormalizer,
        server_catalog: LocalMcpServerCatalog,
        tool_runner: StdioMcpToolRunner,
        rag_top_k: int,
        audit_store: SqliteAuditStore | None = None,
        chat_answer_service: ChatAnswerService | None = None,
    ) -> None:
        self.understanding_service = understanding_service or interpreter
        if self.understanding_service is None:
            raise ValueError("understanding_service is required.")
        self.retriever = retriever
        self.composer = composer
        self.policy_service = policy_service or DefaultExecutionPolicyService()
        self.router = router
        self.normalizer = normalizer
        self.server_catalog = server_catalog
        self.tool_runner = tool_runner
        self.rag_top_k = rag_top_k
        self.audit_store = audit_store
        self.chat_answer_service = chat_answer_service
        self.logger = get_logger(__name__)

    async def orchestrate(self, request: UserRequest) -> NormalizedResponse:
        correlation_id = str(uuid4())
        timing = TimingRecorder()
        trace_recorder = OrchestrationTraceRecorder(correlation_id)

        trace_recorder.start_stage("intake")
        started_at = timing.start()
        understanding = self.understanding_service.understand(request)
        self._record_stage(trace_recorder, correlation_id, "intake", timing, started_at)

        trace_recorder.start_stage("context_retrieval")
        started_at = timing.start()
        retrieved_context = self.retriever.retrieve(
            request.message,
            filters=self._context_filters(request, understanding),
            limit=self.rag_top_k,
        )
        trace_recorder.trace.retrieved_context_sources = list(
            dict.fromkeys(item.source_path for item in retrieved_context.items)
        )
        self._record_stage(
            trace_recorder,
            correlation_id,
            "context_retrieval",
            timing,
            started_at,
            {"source_count": len(trace_recorder.trace.retrieved_context_sources)},
        )

        trace_recorder.start_stage("compose")
        started_at = timing.start()
        enriched = self.composer.compose(correlation_id, request, understanding, retrieved_context)
        self._validate_confirmation(enriched.metadata)
        self._record_stage(trace_recorder, correlation_id, "compose", timing, started_at)

        trace_recorder.start_stage("policy")
        started_at = timing.start()
        policy_decision = self.policy_service.decide(enriched, trace_recorder.trace)
        trace_recorder.trace.policy_decision = policy_decision
        trace_recorder.trace.warnings.extend(policy_decision.warnings)
        if policy_decision.confirmation_id and self.audit_store:
            self.audit_store.create_confirmation(
                confirmation_id=policy_decision.confirmation_id,
                request=request,
                policy_decision=policy_decision,
            )
        self._record_stage(
            trace_recorder,
            correlation_id,
            "policy",
            timing,
            started_at,
            {
                "safety_level": policy_decision.safety_level.value,
                "allow_execution": policy_decision.allow_execution,
            },
        )

        trace_recorder.start_stage("planning")
        started_at = timing.start()
        plan = self.router.create_plan(enriched, policy_decision)
        trace_recorder.trace.selected_target_mcps = plan.target_mcps
        self._log(
            correlation_id,
            "planning",
            timing.stop("planning", started_at),
            {"selected_targets": [target.value for target in plan.target_mcps]},
        )
        trace_recorder.end_stage(
            "planning",
            details={"selected_targets": [target.value for target in plan.target_mcps]},
        )

        trace_recorder.start_stage("mcp_execution")
        started_at = timing.start()
        results = await self.router.execute_plan(enriched, plan, trace_recorder.trace)
        self._record_stage(trace_recorder, correlation_id, "mcp_execution", timing, started_at)

        trace_recorder.start_stage("normalization")
        started_at = timing.start()
        response = self.normalizer.normalize(correlation_id, results, timing.timings)
        response.confirmation_id = policy_decision.confirmation_id
        if policy_decision.confirmation_id:
            response.next_actions = [
                f"Use confirmation_id {policy_decision.confirmation_id} with allow_execution=true to run read-only execution.",
                *response.next_actions,
            ]
        duration_ms = timing.stop("normalization", started_at)
        response.timings["normalization"] = round(duration_ms, 3)
        trace_recorder.end_stage("normalization")
        trace = trace_recorder.complete()
        response.debug["orchestration_trace"] = trace.model_dump(mode="json")
        response.debug["confirmation_id"] = policy_decision.confirmation_id
        execution_trace_raw = self._collect_execution_trace(response)
        response.debug["execution_trace_raw"] = execution_trace_raw
        response.debug["execution_trace_sections"] = self._build_execution_trace_sections(
            execution_trace_raw
        )
        self._record_audit(
            request=request,
            understanding=understanding,
            trace=trace,
            plan=plan,
            policy_decision=policy_decision,
            response=response,
        )
        self._log(correlation_id, "normalization", duration_ms, {"status": response.status.value})
        return response

    async def chat(self, request: ChatRequest) -> ChatResponse:
        user_request = UserRequest(
            message=request.message,
            domain_hint=request.domain_hint,
            tags=request.tags,
            metadata=request.metadata,
        )
        if self.chat_answer_service:
            user_request = self.chat_answer_service.enrich_request(user_request)
        orchestration = await self.orchestrate(user_request)
        if self.chat_answer_service:
            return self.chat_answer_service.compose(user_request, orchestration)
        return ChatAnswerService(api_key=None, model="fallback").compose(
            user_request,
            orchestration,
        )

    async def execute_chat_confirmation(self, confirmation_id: str) -> ChatResponse:
        executed = await self.execute_confirmation(confirmation_id)
        confirmation = self.audit_store.get_confirmation(confirmation_id) if self.audit_store else None
        request = UserRequest.model_validate(confirmation["request"]) if confirmation else UserRequest(
            message=f"Execute confirmation {confirmation_id}"
        )
        if self.chat_answer_service:
            return self.chat_answer_service.compose(request, executed.response)
        return ChatAnswerService(api_key=None, model="fallback").compose(request, executed.response)

    def docs_index_status(self) -> dict[str, object]:
        return self.retriever.status()

    def rebuild_docs_index(self) -> dict[str, object]:
        self.retriever.rebuild()
        return self.retriever.status()

    def mcp_servers_status(self) -> dict[str, object]:
        return self.server_catalog.status()

    def business_rules_status(self) -> dict[str, object]:
        status = self.retriever.status()
        return {
            "docs_dir": status.get("docs_dir"),
            "business_rules": status.get("business_rules", {}),
        }

    def get_audit_event(self, correlation_id: str) -> dict[str, object] | None:
        if not self.audit_store:
            return None
        return self.audit_store.get_audit_event(correlation_id)

    async def execute_confirmation(self, confirmation_id: str) -> ConfirmationExecutionResponse:
        if not self.audit_store:
            raise ValueError("Audit store is not configured.")
        confirmation = self.audit_store.get_confirmation(confirmation_id)
        if not confirmation:
            raise ValueError(f"Confirmation not found: {confirmation_id}")
        if confirmation["status"] != "pending":
            raise ValueError(f"Confirmation is not pending: {confirmation_id}")

        request = UserRequest.model_validate(confirmation["request"])
        metadata = dict(request.metadata)
        metadata["allow_execution"] = True
        metadata["confirmation_id"] = confirmation_id
        response = await self.orchestrate(request.model_copy(update={"metadata": metadata}))
        self.audit_store.mark_confirmation_executed(confirmation_id, response.correlation_id)
        return ConfirmationExecutionResponse(
            confirmation_id=confirmation_id,
            status="executed",
            response=response,
        )

    async def list_mcp_tools(self, server_name: str) -> list[McpToolDefinition]:
        server = self.server_catalog.get(server_name)
        if not server:
            raise ValueError(f"MCP server not found: {server_name}")
        return await self.tool_runner.list_tools(server)

    async def call_mcp_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, object],
    ) -> McpToolCallResponse:
        server = self.server_catalog.get(server_name)
        if not server:
            raise ValueError(f"MCP server not found: {server_name}")
        return await self.tool_runner.call_tool(server, tool_name, arguments)

    def _context_filters(self, request: UserRequest, understanding) -> dict[str, object]:
        filters: dict[str, object] = {}
        if request.tags:
            filters["tags"] = request.tags
        if understanding.domain.value not in {"analytics", "general", "unknown"}:
            filters["domain"] = understanding.domain.value
        return filters

    def _validate_confirmation(self, metadata: dict[str, object]) -> None:
        confirmation_id = metadata.get("confirmation_id")
        if not confirmation_id or not metadata.get("allow_execution"):
            return
        if self.audit_store and self.audit_store.is_pending_confirmation(str(confirmation_id)):
            return
        metadata.pop("confirmation_id", None)

    def _log(
        self,
        correlation_id: str,
        stage: str,
        duration_ms: float,
        extra: dict[str, object] | None = None,
    ) -> None:
        log_stage(
            self.logger,
            correlation_id=correlation_id,
            stage=stage,
            status=(extra or {}).pop("status", "success"),
            duration_ms=duration_ms,
            extra=extra,
        )

    def _record_stage(
        self,
        trace_recorder: OrchestrationTraceRecorder,
        correlation_id: str,
        stage: str,
        timing: TimingRecorder,
        started_at: float,
        details: dict[str, object] | None = None,
    ) -> None:
        duration_ms = timing.stop(stage, started_at)
        trace_recorder.end_stage(stage, details=details)
        self._log(correlation_id, stage, duration_ms, details)

    def _record_audit(
        self,
        *,
        request: UserRequest,
        understanding,
        trace,
        plan,
        policy_decision,
        response: NormalizedResponse,
    ) -> None:
        if not self.audit_store:
            return
        self.audit_store.record_response(
            request=request,
            understanding=understanding.model_dump(mode="json"),
            retrieved_context_sources=trace.retrieved_context_sources,
            policy_decision=policy_decision,
            plan=plan.model_dump(mode="json"),
            response=response,
        )

    def _collect_execution_trace(self, response: NormalizedResponse) -> list[dict[str, object]]:
        steps: list[dict[str, object]] = []
        for result in response.specialist_results:
            debug = result.debug if isinstance(result.debug, dict) else {}
            trace_steps = debug.get("execution_trace")
            if isinstance(trace_steps, list):
                for step in trace_steps:
                    if isinstance(step, dict):
                        steps.append(step)
        return steps

    def _build_execution_trace_sections(
        self,
        steps: list[dict[str, object]],
    ) -> dict[str, list[dict[str, object]]]:
        executed: list[dict[str, object]] = []
        validation: list[dict[str, object]] = []
        calculation: list[dict[str, object]] = []
        result: list[dict[str, object]] = []

        for step in steps:
            executed.append(
                {
                    "target_mcp": step.get("target_mcp"),
                    "tool_name": step.get("tool_name"),
                    "operation": step.get("operation"),
                    "status": step.get("status"),
                    "started_at": step.get("started_at"),
                    "duration_ms": step.get("duration_ms"),
                }
            )
            validation.append(
                {
                    "tool_name": step.get("tool_name"),
                    "operation": step.get("operation"),
                    "validation": step.get("validation") or {},
                    "errors": step.get("errors") or [],
                    "warnings": step.get("warnings") or [],
                }
            )
            calculation.append(
                {
                    "tool_name": step.get("tool_name"),
                    "operation": step.get("operation"),
                    "calculation": step.get("calculation") or {},
                }
            )
            result.append(
                {
                    "tool_name": step.get("tool_name"),
                    "operation": step.get("operation"),
                    "output_summary": step.get("output_summary") or {},
                    "output_sample": step.get("output_sample") or [],
                }
            )

        if not steps:
            calculation.append(
                {
                    "tool_name": None,
                    "operation": None,
                    "calculation": {"note": "nao houve execucao de medida"},
                }
            )

        return {
            "executado": executed,
            "validacao": validation,
            "calculo": calculation,
            "resultado": result,
        }


def create_orchestration_service(settings: Settings | None = None) -> OrchestrationService:
    settings = settings or Settings()
    server_catalog = LocalMcpServerCatalog(settings.resolved_mcps_dir())
    tool_runner = StdioMcpToolRunner()
    registry = DefaultMcpClientRegistry(
        server_catalog=server_catalog,
        tool_runner=tool_runner,
    )
    router = ExecutionRouter(registry)
    retriever = LocalContextRetriever(
        settings.resolved_docs_dir(),
        chunk_size=settings.rag_chunk_size,
    )
    understanding_service = _understanding_service(settings)
    return OrchestrationService(
        understanding_service=understanding_service,
        retriever=retriever,
        composer=DefaultContextComposer(),
        policy_service=DefaultExecutionPolicyService(),
        router=router,
        normalizer=DefaultResponseNormalizer(),
        server_catalog=server_catalog,
        tool_runner=tool_runner,
        rag_top_k=settings.rag_top_k,
        audit_store=SqliteAuditStore(settings.resolved_audit_db_path()),
        chat_answer_service=ChatAnswerService(
            api_key=settings.resolved_openai_api_key(),
            model=settings.resolved_openai_model(),
            groq_api_key=settings.resolved_groq_api_key(),
            groq_model=settings.resolved_groq_model(),
        ),
    )


def _understanding_service(settings: Settings):
    if settings.resolved_intelligence_mode() == "openai":
        return OpenAIRequestUnderstandingService(
            api_key=settings.resolved_openai_api_key(),
            model=settings.resolved_openai_model(),
        )
    return HeuristicRequestUnderstandingService()
