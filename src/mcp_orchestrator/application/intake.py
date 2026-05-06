from __future__ import annotations

import json
from typing import Any
from collections.abc import Iterable

import httpx
from pydantic import ValidationError

from mcp_orchestrator.domain.enums import Domain, McpTarget, RequestedAction, RiskLevel, TaskType
from mcp_orchestrator.domain.models import RequestUnderstanding, UserRequest


class HeuristicRequestUnderstandingService:
    power_bi_terms = (
        "power bi",
        "power_bi",
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
    read_terms = (
        "show",
        "list",
        "find",
        "query",
        "select",
        "read",
        "inspect",
        "verifica",
        "verifique",
        "valida",
        "valide",
        "compare",
    )
    write_terms = ("insert", "update", "delete", "drop", "create", "alter", "truncate", "modify", "rename")
    side_effect_terms = ("send", "email", "publish", "refresh", "deploy", "execute")
    # New: terms indicating user wants actual numeric values, not metadata
    value_query_terms = (
        "quantos",
        "quanto",
        "how many",
        "how much",
        "total",
        "qual",
        "what",
        "qual foi",
        "qual é",
        "qual o",
        "quanto foi",
        "quanto é",
        "em fevereiro",
        "em janeiro",
        "em",
        "during",
        "em 2026",
        "2026",
        "fevereiro de",
        "janeiro de",
        "março de",
        "mês",
        "month",
        "ano",
        "year",
        "mais",
        "maior",
        "top",
        "ranking",
        "lider",
        "lidera",
        "verifica",
        "validar",
    )

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
            # Detect if user is asking for actual measure values (quantos, total, etc)
            if self._is_value_query(text):
                return TaskType.MEASURE_VALUE_QUERY
            return TaskType.SEMANTIC_MODEL_QUERY
        if McpTarget.POSTGRESQL in candidates or McpTarget.SQL_SERVER in candidates:
            return TaskType.SQL_QUERY
        if McpTarget.EXCEL in candidates:
            return TaskType.TABULAR_EXTRACTION
        if self._contains_any(text, self.docs_terms):
            return TaskType.DOCUMENTATION_LOOKUP
        return TaskType.UNKNOWN
    
    def _is_value_query(self, text: str) -> bool:
        """
        Detect if user is asking for actual measure values, not just metadata.
        Patterns: "quantos X eu tive", "qual foi o total", "total de X", etc.
        """
        if self._contains_any(
            text,
            (
                "semantic model",
                "modelo semantico",
                "modelo semântico",
                "metadata",
                "medida que mostra",
                "qual a medida",
                "qual medida",
                "definicao",
                "definição",
                "formula",
                "fórmula",
            ),
        ):
            return False

        # Check for value query terms combined with measure-like words
        has_value_term = self._contains_any(text, self.value_query_terms)
        has_measure_term = self._contains_any(
            text,
            (
                "medida",
                "valor",
                "total",
                "saldo",
                "contratos",
                "movimento",
                "movimentacao",
                "distrato",
                "proposta",
                "propostas",
                "vgv",
                "liner",
                "closer",
                "captador",
                "promotor",
                "lider",
            ),
        )
        
        return has_value_term and has_measure_term

    def _requested_action(self, text: str, task_type: TaskType) -> RequestedAction:
        if "refresh" in text:
            return RequestedAction.REFRESH
        if self._contains_any(text, self.write_terms):
            return RequestedAction.WRITE
        if task_type == TaskType.SEMANTIC_MODEL_INSPECTION:
            return RequestedAction.INSPECT_MODEL
        if task_type == TaskType.MEASURE_VALUE_QUERY:
            return RequestedAction.EXECUTE_QUERY
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
            TaskType.MEASURE_VALUE_QUERY,
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


class OpenAIRequestUnderstandingService:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        fallback: HeuristicRequestUnderstandingService | None = None,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.fallback = fallback or HeuristicRequestUnderstandingService()
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def understand(self, request: UserRequest) -> RequestUnderstanding:
        if not self.api_key:
            return self.fallback.understand(request)

        try:
            payload = self._responses_payload(request)
            with httpx.Client(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = client.post(
                    "https://api.openai.com/v1/responses",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
            return self._parse_response(response.json(), request)
        except (httpx.HTTPError, KeyError, TypeError, ValueError, ValidationError):
            return self.fallback.understand(request)

    def interpret(self, request: UserRequest) -> RequestUnderstanding:
        return self.understand(request)

    def _responses_payload(self, request: UserRequest) -> dict[str, Any]:
        schema = RequestUnderstanding.model_json_schema()
        return {
            "model": self.model,
            "input": [
                {
                    "role": "developer",
                    "content": (
                        "Classify the user request for an MCP orchestrator. "
                        "Return only fields that satisfy the provided JSON schema. "
                        "Use the user language for reasoning_summary when useful. "
                        "Never invent a target MCP when the request does not mention or imply one."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "message": request.message,
                            "domain_hint": request.domain_hint,
                            "tags": request.tags,
                            "metadata": request.metadata,
                            "allowed_domains": [item.value for item in Domain],
                            "allowed_task_types": [item.value for item in TaskType],
                            "allowed_actions": [item.value for item in RequestedAction],
                            "allowed_targets": [item.value for item in McpTarget],
                            "allowed_risk_levels": [item.value for item in RiskLevel],
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "request_understanding",
                    "schema": schema,
                    "strict": True,
                }
            },
        }

    def _parse_response(
        self,
        payload: dict[str, Any],
        request: UserRequest,
    ) -> RequestUnderstanding:
        text = self._extract_output_text(payload)
        data = json.loads(text)
        data.setdefault("original_request", request.message)
        return RequestUnderstanding.model_validate(data)

    def _extract_output_text(self, payload: dict[str, Any]) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        output = payload.get("output", [])
        if not isinstance(output, list):
            raise ValueError("OpenAI response output is not a list.")

        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content", [])
            if not isinstance(content, list):
                continue
            for content_item in content:
                if not isinstance(content_item, dict):
                    continue
                text = content_item.get("text")
                if isinstance(text, str):
                    parts.append(text)

        joined = "".join(parts).strip()
        if not joined:
            raise ValueError("OpenAI response did not include output text.")
        return joined
