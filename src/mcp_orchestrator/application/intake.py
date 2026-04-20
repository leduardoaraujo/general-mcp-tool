from __future__ import annotations

from collections.abc import Iterable

from mcp_orchestrator.domain.enums import Domain, McpTarget, RequestedAction, RiskLevel, TaskType
from mcp_orchestrator.domain.models import RequestUnderstanding, UserRequest


class HeuristicRequestUnderstandingService:
    power_bi_terms = (
        "power bi",
        "powerbi",
        "semantic model",
        "modelo semantico",
        "modelo semântico",
        "measure",
        "measures",
        "medida",
        "medidas",
        "dax",
        "dataset",
        "fabric semantic model",
    )
    postgresql_terms = ("postgres", "postgresql")
    sql_server_terms = ("sql server", "mssql", "t-sql", "tsql")
    sql_terms = ("sql", "query", "consulta", "table", "tabela", "join", "database")
    excel_terms = ("excel", "xlsx", "spreadsheet", "worksheet", "planilha")
    docs_terms = ("documentation", "docs", "manual", "playbook", "documentacao")
    preview_terms = ("preview", "prepare", "generate", "safe sql", "do not execute")
    read_terms = ("show", "list", "find", "query", "select", "read", "inspect")
    write_terms = ("insert", "update", "delete", "drop", "create", "alter", "truncate", "modify", "rename")
    side_effect_terms = ("send", "email", "publish", "refresh", "deploy", "execute")

    def understand(self, request: UserRequest) -> RequestUnderstanding:
        text = self._normalize(f"{request.message} {request.domain_hint or ''}")
        candidates = self._candidate_mcps(text)
        domain = self._domain(text, candidates)
        task_type = self._task_type(text, candidates)
        requested_action = self._requested_action(text, task_type)
        risk_level = self._risk_level(text, requested_action)

        return RequestUnderstanding(
            original_request=request.message,
            intent=self._intent(task_type, domain),
            domain=domain,
            task_type=task_type,
            requested_action=requested_action,
            target_preference=self._target_preference(candidates),
            relevant_sources=self._relevant_sources(task_type, domain),
            candidate_mcps=candidates,
            constraints=self._constraints(text),
            ambiguities=self._ambiguities(text, candidates, task_type),
            confidence=self._confidence(text, candidates),
            risk_level=risk_level,
            reasoning_summary=self._reasoning_summary(
                task_type,
                domain,
                requested_action,
                candidates,
                risk_level,
            ),
        )

    def interpret(self, request: UserRequest) -> RequestUnderstanding:
        return self.understand(request)

    def _candidate_mcps(self, text: str) -> list[McpTarget]:
        candidates: list[McpTarget] = []
        if self._contains_any(text, self.power_bi_terms):
            candidates.append(McpTarget.POWER_BI)
        if self._contains_any(text, self.postgresql_terms):
            candidates.append(McpTarget.POSTGRESQL)
        if self._contains_any(text, self.sql_server_terms):
            candidates.append(McpTarget.SQL_SERVER)
        if self._contains_any(text, self.sql_terms) and not candidates:
            candidates.append(McpTarget.POSTGRESQL)
        if self._contains_any(text, self.excel_terms):
            candidates.append(McpTarget.EXCEL)
        return candidates

    def _domain(self, text: str, candidates: list[McpTarget]) -> Domain:
        if len(candidates) > 1:
            return Domain.ANALYTICS
        if candidates == [McpTarget.POWER_BI]:
            return Domain.POWER_BI
        if candidates == [McpTarget.POSTGRESQL]:
            return Domain.POSTGRESQL
        if candidates == [McpTarget.SQL_SERVER]:
            return Domain.SQL_SERVER
        if candidates == [McpTarget.EXCEL]:
            return Domain.EXCEL
        if self._contains_any(text, self.docs_terms):
            return Domain.GENERAL
        return Domain.UNKNOWN

    def _task_type(self, text: str, candidates: list[McpTarget]) -> TaskType:
        if len(candidates) > 1:
            return TaskType.COMPOSITE
        if McpTarget.POWER_BI in candidates:
            if "dax" in text:
                return TaskType.DAX_QUERY
            if self._contains_any(text, ("list", "inspect", "metadata", "tables", "measures")):
                return TaskType.SEMANTIC_MODEL_INSPECTION
            return TaskType.SEMANTIC_MODEL_QUERY
        if McpTarget.POSTGRESQL in candidates or McpTarget.SQL_SERVER in candidates:
            return TaskType.SQL_QUERY
        if McpTarget.EXCEL in candidates:
            return TaskType.TABULAR_EXTRACTION
        if self._contains_any(text, self.docs_terms):
            return TaskType.DOCUMENTATION_LOOKUP
        return TaskType.UNKNOWN

    def _requested_action(self, text: str, task_type: TaskType) -> RequestedAction:
        if "refresh" in text:
            return RequestedAction.REFRESH
        if self._contains_any(text, self.write_terms):
            return RequestedAction.WRITE
        if task_type == TaskType.SEMANTIC_MODEL_INSPECTION:
            return RequestedAction.INSPECT_MODEL
        if task_type == TaskType.DOCUMENTATION_LOOKUP or "schema" in text:
            return RequestedAction.INSPECT_SCHEMA
        if self._contains_any(text, self.preview_terms):
            return RequestedAction.GENERATE_QUERY
        if self._contains_any(text, self.read_terms):
            return RequestedAction.READ
        return RequestedAction.UNKNOWN

    def _target_preference(self, candidates: list[McpTarget]) -> McpTarget | None:
        if len(candidates) == 1:
            return candidates[0]
        return None

    def _relevant_sources(self, task_type: TaskType, domain: Domain) -> list[str]:
        sources = ["business_rules", "schemas", "technical_docs"]
        if task_type in {
            TaskType.SEMANTIC_MODEL_QUERY,
            TaskType.SEMANTIC_MODEL_INSPECTION,
            TaskType.DAX_QUERY,
            TaskType.SQL_QUERY,
            TaskType.COMPOSITE,
        }:
            sources.extend(["playbooks", "examples"])
        if task_type == TaskType.TABULAR_EXTRACTION:
            sources.extend(["examples", "playbooks"])
        if domain == Domain.GENERAL:
            sources = ["technical_docs", "playbooks", "business_rules"]
        return list(dict.fromkeys(sources))

    def _constraints(self, text: str) -> list[str]:
        constraints: list[str] = []
        if "do not execute" in text or "sem executar" in text:
            constraints.append("Do not execute external operations.")
        if "read only" in text or "somente leitura" in text:
            constraints.append("Read-only execution.")
        return constraints

    def _ambiguities(
        self,
        text: str,
        candidates: list[McpTarget],
        task_type: TaskType,
    ) -> list[str]:
        ambiguities: list[str] = []
        if not candidates and task_type != TaskType.DOCUMENTATION_LOOKUP:
            ambiguities.append("No specialist MCP target was identified.")
        if len(candidates) > 1:
            ambiguities.append("Multiple specialist MCP targets may be relevant.")
        if task_type == TaskType.SQL_QUERY and "sql" in text and not self._contains_any(text, self.postgresql_terms + self.sql_server_terms):
            ambiguities.append("SQL dialect was not explicit; PostgreSQL is the Phase 1 default.")
        return ambiguities

    def _risk_level(self, text: str, requested_action: RequestedAction) -> RiskLevel:
        if requested_action == RequestedAction.WRITE:
            return RiskLevel.HIGH
        if requested_action == RequestedAction.REFRESH:
            return RiskLevel.HIGH
        if self._contains_any(text, self.side_effect_terms) and requested_action != RequestedAction.GENERATE_QUERY:
            return RiskLevel.MEDIUM
        if requested_action == RequestedAction.READ:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _reasoning_summary(
        self,
        task_type: TaskType,
        domain: Domain,
        requested_action: RequestedAction,
        candidates: list[McpTarget],
        risk_level: RiskLevel,
    ) -> str:
        target_text = ", ".join(target.value for target in candidates) or "no specialist target"
        return (
            f"Classified as {task_type.value} in {domain.value}; "
            f"requested action is {requested_action.value}; "
            f"candidate targets: {target_text}; risk is {risk_level.value}."
        )

    def _intent(self, task_type: TaskType, domain: Domain) -> str:
        if task_type == TaskType.COMPOSITE:
            return "Coordinate multiple data sources."
        if task_type == TaskType.UNKNOWN:
            return "Understand user request."
        return f"Handle {task_type.value} for {domain.value}."

    def _confidence(self, text: str, candidates: list[McpTarget]) -> float:
        signal_count = len(candidates)
        if self._contains_any(text, self.docs_terms):
            signal_count += 1
        return min(0.95, 0.25 + (signal_count * 0.2))

    def _contains_any(self, text: str, terms: Iterable[str]) -> bool:
        return any(term in text for term in terms)

    def _normalize(self, value: str) -> str:
        return " ".join(value.lower().split())


HeuristicRequestInterpreter = HeuristicRequestUnderstandingService
