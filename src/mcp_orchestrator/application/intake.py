from __future__ import annotations

from collections.abc import Iterable

from mcp_orchestrator.domain.enums import Domain, McpTarget, TaskType
from mcp_orchestrator.domain.models import OrchestrateRequest, RequestInterpretation


class HeuristicRequestInterpreter:
    power_bi_terms = (
        "power bi",
        "semantic model",
        "modelo semantico",
        "modelo semântico",
        "measure",
        "dax",
        "dataset",
    )
    postgresql_terms = ("postgres", "postgresql")
    sql_server_terms = ("sql server", "mssql", "t-sql", "tsql")
    sql_terms = ("sql", "query", "consulta", "table", "tabela", "join")
    excel_terms = ("excel", "xlsx", "spreadsheet", "worksheet", "planilha")
    docs_terms = ("documentacao", "documentação", "docs", "manual", "playbook")

    def interpret(self, request: OrchestrateRequest) -> RequestInterpretation:
        text = self._normalize(f"{request.message} {request.domain_hint or ''}")
        candidates = self._candidate_mcps(text)
        domain = self._domain(text, candidates)
        task_type = self._task_type(text, candidates)
        sources = self._relevant_sources(task_type, domain)
        constraints = self._constraints(text)

        return RequestInterpretation(
            original_request=request.message,
            intent=self._intent(task_type, domain),
            domain=domain,
            task_type=task_type,
            relevant_sources=sources,
            candidate_mcps=candidates,
            constraints=constraints,
            confidence=self._confidence(text, candidates),
        )

    def _candidate_mcps(self, text: str) -> list[McpTarget]:
        candidates: list[McpTarget] = []
        if self._contains_any(text, self.power_bi_terms):
            candidates.append(McpTarget.POWER_BI)
        if self._contains_any(text, self.postgresql_terms):
            candidates.append(McpTarget.POSTGRESQL)
        if self._contains_any(text, self.sql_server_terms):
            candidates.append(McpTarget.SQL_SERVER)
        if self._contains_any(text, self.sql_terms):
            if McpTarget.POSTGRESQL not in candidates:
                candidates.append(McpTarget.POSTGRESQL)
            if McpTarget.SQL_SERVER not in candidates:
                candidates.append(McpTarget.SQL_SERVER)
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
            return TaskType.SEMANTIC_MODEL_QUERY
        if McpTarget.POSTGRESQL in candidates or McpTarget.SQL_SERVER in candidates:
            return TaskType.SQL_QUERY
        if McpTarget.EXCEL in candidates:
            return TaskType.TABULAR_EXTRACTION
        if self._contains_any(text, self.docs_terms):
            return TaskType.DOCUMENTATION_LOOKUP
        return TaskType.UNKNOWN

    def _relevant_sources(self, task_type: TaskType, domain: Domain) -> list[str]:
        sources = ["business_rules", "schemas"]
        if task_type in {TaskType.SEMANTIC_MODEL_QUERY, TaskType.SQL_QUERY}:
            sources.extend(["playbooks", "examples"])
        if task_type == TaskType.TABULAR_EXTRACTION:
            sources.extend(["examples", "playbooks"])
        if domain == Domain.GENERAL:
            sources = ["playbooks", "business_rules"]
        return list(dict.fromkeys(sources))

    def _constraints(self, text: str) -> list[str]:
        constraints: list[str] = []
        if "sem executar" in text or "do not execute" in text:
            constraints.append("Do not execute external operations.")
        if "somente leitura" in text or "read only" in text:
            constraints.append("Read-only execution.")
        return constraints

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
