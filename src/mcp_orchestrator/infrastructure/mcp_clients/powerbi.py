from __future__ import annotations

import json
import csv
import io
import re
import unicodedata
from time import perf_counter
from typing import Any, Protocol

from mcp_orchestrator.domain.enums import Domain, McpTarget, ResultStatus, TaskType
from mcp_orchestrator.domain.models import (
    EnrichedRequest,
    ExecutionPlan,
    McpClientCapability,
    McpToolCallResponse,
    SpecialistExecutionRequest,
    SpecialistExecutionResult,
)
from mcp_orchestrator.infrastructure.mcp_servers import LocalMcpServerCatalog, McpServerDefinition


class ToolRunner(Protocol):
    async def call_tool(
        self,
        server: McpServerDefinition,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> McpToolCallResponse:
        ...


class PowerBiMcpClient:
    name = "power_bi"
    target = McpTarget.POWER_BI

    def __init__(
        self,
        *,
        server_catalog: LocalMcpServerCatalog,
        tool_runner: ToolRunner,
    ) -> None:
        self.server_catalog = server_catalog
        self.tool_runner = tool_runner

    def can_handle(self, plan: ExecutionPlan, request: EnrichedRequest) -> bool:
        return (
            self.target in plan.target_mcps
            or request.understanding.domain == Domain.POWER_BI
            or request.understanding.task_type
            in {
                TaskType.SEMANTIC_MODEL_QUERY,
                TaskType.SEMANTIC_MODEL_INSPECTION,
                TaskType.DAX_QUERY,
            }
        )

    def capabilities(self) -> McpClientCapability:
        return McpClientCapability(
            name=self.name,
            target=self.target,
            supports_preview=True,
            supports_read=True,
            supports_write=False,
            supports_side_effects=False,
            semantic_model_inspection=True,
            table_listing=True,
            measure_listing=True,
            dax_support=True,
            metadata_read=True,
            refresh_support=False,
            model_write_support=False,
            side_effect_support=False,
            default_tool="run_guided_modeling_request",
            supported_tools=[
                "run_guided_modeling_request",
                "list_semantic_model_tables",
                "list_semantic_model_measures",
                "preview_dax",
            ],
            notes=[
                "Phase 3 orchestration uses safe semantic-model inspection and preview workflows.",
                "Refresh and model mutation remain blocked by execution policy by default.",
            ],
        )

    async def execute(self, request: SpecialistExecutionRequest) -> SpecialistExecutionResult:
        started_at = perf_counter()
        server = self.server_catalog.get(self.name)
        if server is None:
            return self._missing_server_result(request, started_at)

        if request.tool_name == "run_guided_modeling_request":
            response = await self._execute_guided_modeling_request(server, request)
            if response is None:
                response = await self.tool_runner.call_tool(
                    server,
                    request.tool_name,
                    request.arguments,
                )
        else:
            response = await self.tool_runner.call_tool(
                server,
                request.tool_name,
                request.arguments,
            )

        duration_ms = (perf_counter() - started_at) * 1000
        status = ResultStatus.ERROR if response.is_error else ResultStatus.SUCCESS
        errors = self._errors(response) if response.is_error else []

        return SpecialistExecutionResult(
            mcp_name=self.name,
            target=self.target,
            status=status,
            summary=self._summary(response),
            structured_data=self._structured_data(response),
            sources_used=self._sources(request),
            trace=[
                f"Power BI MCP called tool {request.tool_name}.",
                "Power BI orchestration used policy-controlled semantic execution.",
            ],
            errors=errors,
            warnings=self._warnings(request),
            duration_ms=duration_ms,
            debug={
                "server_name": response.server_name,
                "tool_name": response.tool_name,
                "arguments": request.arguments,
                "policy_decision": request.policy_decision.model_dump(mode="json")
                if request.policy_decision
                else None,
                "raw_result": response.raw_result,
            },
        )

    async def _execute_guided_modeling_request(
        self,
        server: McpServerDefinition,
        request: SpecialistExecutionRequest,
    ) -> McpToolCallResponse | None:
        call_with_session = getattr(self.tool_runner, "call_with_session", None)
        if call_with_session is None:
            return None

        return await call_with_session(
            server,
            lambda caller: self._guided_modeling_session(caller, request),
        )

    async def _guided_modeling_session(
        self,
        caller: Any,
        request: SpecialistExecutionRequest,
    ) -> McpToolCallResponse:
        operations: list[dict[str, Any]] = []
        local_instances = await caller.call_tool(
            "connection_operations",
            {"request": {"operation": "ListLocalInstances"}},
        )
        operations.append(self._operation_record("connection_operations", local_instances))
        if local_instances.is_error:
            return self._aggregate_guided_response(
                is_error=True,
                summary="Power BI local instance discovery failed.",
                operations=operations,
            )

        instances = self._payload_data(local_instances)
        if not instances:
            return self._aggregate_guided_response(
                is_error=True,
                summary="No local Power BI Desktop or Analysis Services instance was found.",
                operations=operations,
            )

        instance = instances[0]
        connect = await caller.call_tool(
            "connection_operations",
            {
                "request": {
                    "operation": "Connect",
                    "connectionString": instance["connectionString"],
                }
            },
        )
        operations.append(self._operation_record("connection_operations", connect))
        if connect.is_error:
            return self._aggregate_guided_response(
                is_error=True,
                summary="Power BI local instance connection failed.",
                operations=operations,
                connection=instance,
            )

        original_user_request = str(request.enriched_request.original_request)
        user_request = "\n".join(
            part
            for part in [
                original_user_request,
                str(request.arguments.get("request") or ""),
            ]
            if part
        )
        guided_data: dict[str, Any] = {
            "connection": instance,
            "requested_analysis": user_request,
        }

        summarize_model = self._should_summarize_model(original_user_request)

        if self._should_list_tables(original_user_request) or summarize_model:
            tables = await caller.call_tool(
                "table_operations",
                {"request": {"operation": "List", "filter": {"maxResults": 200}}},
            )
            operations.append(self._operation_record("table_operations", tables))
            guided_data["tables"] = self._payload_data(tables)

        if self._should_list_columns(original_user_request):
            table_names = self._matching_table_names(
                guided_data.get("tables"),
                original_user_request,
            )
            if not table_names:
                if "tables" not in guided_data:
                    tables = await caller.call_tool(
                        "table_operations",
                        {"request": {"operation": "List", "filter": {"maxResults": 200}}},
                    )
                    operations.append(self._operation_record("table_operations", tables))
                    guided_data["tables"] = self._payload_data(tables)
                table_names = self._matching_table_names(
                    guided_data.get("tables"),
                    original_user_request,
                )

            columns_by_table: dict[str, Any] = {}
            for table_name in table_names[:5]:
                columns = await caller.call_tool(
                    "column_operations",
                    {
                        "request": {
                            "operation": "List",
                            "filter": {"tableNames": [table_name], "maxResults": 300},
                        }
                    },
                )
                operations.append(self._operation_record("column_operations", columns))
                columns_by_table[table_name] = self._flatten_column_payload(
                    self._payload_data(columns)
                )
            if columns_by_table:
                guided_data["columns"] = columns_by_table

        should_execute_measure_query = self._should_execute_measure_query(request)

        if should_execute_measure_query or self._should_list_measures(original_user_request) or summarize_model:
            measures = await caller.call_tool(
                "measure_operations",
                {"request": {"operation": "List", "filter": {"maxResults": 200}}},
            )
            operations.append(self._operation_record("measure_operations", measures))
            measure_list = self._payload_data(measures)
            guided_data["measures"] = measure_list

            matches = self._matching_measures(measure_list, original_user_request)
            if matches and should_execute_measure_query:
                guided_data["matching_measures"] = matches
                query_result = await self._execute_measure_query(
                    caller,
                    original_user_request,
                    matches,
                )
                if query_result is not None:
                    operations.append(query_result["operation"])
                    guided_data.update(query_result["guided_data"])

            if matches and self._should_get_measure_definitions(original_user_request):
                measure_definitions = await caller.call_tool(
                    "measure_operations",
                    {
                        "request": {
                            "operation": "Get",
                            "references": [{"name": measure["name"]} for measure in matches[:5]],
                        }
                    },
                )
                operations.append(
                    self._operation_record("measure_operations", measure_definitions)
                )
                guided_data["matching_measures"] = matches
                guided_data["measure_definitions"] = self._payload_data(measure_definitions)
            elif matches:
                guided_data["matching_measures"] = matches

        if not any(
            key in guided_data
            for key in {"tables", "measures", "measure_definitions", "columns"}
        ):
            stats = await caller.call_tool(
                "model_operations",
                {"request": {"operation": "GetStats"}},
            )
            operations.append(self._operation_record("model_operations", stats))
            guided_data["model_stats"] = self._payload_data(stats)

        return self._aggregate_guided_response(
            is_error=any(record["is_error"] for record in operations),
            summary=self._guided_summary(guided_data),
            operations=operations,
            connection=instance,
            guided_data=guided_data,
        )

    def _aggregate_guided_response(
        self,
        *,
        is_error: bool,
        summary: str,
        operations: list[dict[str, Any]],
        connection: dict[str, Any] | None = None,
        guided_data: dict[str, Any] | None = None,
    ) -> McpToolCallResponse:
        structured_content = {
            "summary": summary,
            "connection": connection,
            "operations": operations,
        }
        if guided_data:
            structured_content.update(guided_data)
        return McpToolCallResponse(
            server_name=self.name,
            tool_name="run_guided_modeling_request",
            is_error=is_error,
            content=[summary],
            structured_content=structured_content,
            raw_result={"transport": "stdio", "operations": operations},
        )

    def _guided_summary(self, guided_data: dict[str, Any]) -> str:
        ranking_analysis = guided_data.get("ranking_analysis")
        if isinstance(ranking_analysis, dict):
            entity_name = ranking_analysis.get("entity_name")
            entity_type = ranking_analysis.get("entity_type")
            measure_name = ranking_analysis.get("measure_name")
            entity_value = ranking_analysis.get("entity_value")
            entity_rank = ranking_analysis.get("entity_rank")
            top_entity_name = ranking_analysis.get("top_entity_name")
            top_entity_value = ranking_analysis.get("top_entity_value")
            is_top_entity = ranking_analysis.get("is_top_entity")
            if is_top_entity is True:
                return (
                    f"{entity_name} is the top {entity_type} for {measure_name} "
                    f"with {entity_value}."
                )
            if entity_name and top_entity_name:
                return (
                    f"{entity_name} is not the top {entity_type} for {measure_name}. "
                    f"{top_entity_name} leads with {top_entity_value}; "
                    f"{entity_name} is ranked {entity_rank} with {entity_value}."
                )

        dax_query_results = guided_data.get("dax_query_results")
        if isinstance(dax_query_results, dict):
            rows = dax_query_results.get("rows")
            if isinstance(rows, list) and rows:
                return "Executed Power BI DAX validation successfully."

        columns = guided_data.get("columns")
        if isinstance(columns, dict) and columns:
            table_name, table_columns = next(iter(columns.items()))
            if isinstance(table_columns, list):
                return f"Found {len(table_columns)} column(s) in table '{table_name}'."
            return f"Retrieved columns for table '{table_name}'."

        definitions = guided_data.get("measure_definitions")
        if isinstance(definitions, list) and definitions:
            primary = definitions[0]
            expression = primary.get("expression")
            if expression:
                return f"Measure '{primary.get('name')}' uses expression: {expression}"
            return f"Found measure '{primary.get('name')}'."

        matches = guided_data.get("matching_measures")
        if isinstance(matches, list) and matches:
            return f"Found {len(matches)} matching Power BI measure(s)."

        tables = guided_data.get("tables")
        measures = guided_data.get("measures")
        if isinstance(tables, list) and isinstance(measures, list):
            return f"Found {len(tables)} table(s) and {len(measures)} measure(s) in the Power BI model."
        if isinstance(tables, list):
            return f"Found {len(tables)} table(s) in the Power BI model."
        if isinstance(measures, list):
            return f"Found {len(measures)} measure(s) in the Power BI model."

        stats = guided_data.get("model_stats")
        if isinstance(stats, dict):
            return "Retrieved Power BI semantic model statistics."
        return "Completed safe Power BI semantic-model inspection."

    async def _execute_measure_query(
        self,
        caller: Any,
        user_request: str,
        matches: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        measure = self._best_measure_match(matches, user_request)
        if not measure:
            return None

        measure_name = measure.get("name")
        if not isinstance(measure_name, str):
            return None

        dimension = self._ranking_dimension(user_request)
        if dimension and self._is_ranking_query(user_request):
            dax_query = self._build_ranking_validation_query(
                user_request=user_request,
                measure_name=measure_name,
                table_name=dimension["table_name"],
                column_name=dimension["column_name"],
                entity_type=dimension["entity_type"],
            )
        else:
            dax_query = f'EVALUATE ROW("MetricValue", [{measure_name}])'

        dax_response = await caller.call_tool(
            "dax_query_operations",
            {
                "request": {
                    "operation": "Execute",
                    "query": dax_query,
                    "maxRows": 20,
                    "timeoutSeconds": 120,
                }
            },
        )
        operation = self._operation_record("dax_query_operations", dax_response)
        rows = self._extract_dax_rows(dax_response)
        guided_data: dict[str, Any] = {
            "dax_query_results": {
                "query": dax_query,
                "rows": rows,
                "measure_name": measure_name,
            }
        }

        ranking_analysis = self._build_ranking_analysis(rows, measure_name)
        if ranking_analysis:
            guided_data["ranking_analysis"] = ranking_analysis

        return {"operation": operation, "guided_data": guided_data}

    def _operation_record(
        self,
        tool_name: str,
        response: McpToolCallResponse,
    ) -> dict[str, Any]:
        payload = self._payload(response)
        operation = payload.get("operation") if isinstance(payload, dict) else None
        return {
            "tool_name": tool_name,
            "operation": operation,
            "is_error": response.is_error,
            "content": response.content,
            "payload": payload,
        }

    def _payload(self, response: McpToolCallResponse) -> Any:
        if response.structured_content is not None:
            return response.structured_content
        for content in response.content:
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                continue
        return {"content": response.content}

    def _payload_data(self, response: McpToolCallResponse) -> Any:
        payload = self._payload(response)
        if isinstance(payload, dict):
            results = payload.get("results")
            if isinstance(results, list):
                return [
                    item["data"]
                    for item in results
                    if isinstance(item, dict) and item.get("success") and "data" in item
                ]
            return payload.get("data")
        return payload

    def _should_list_tables(self, user_request: str) -> bool:
        normalized = self._normalize(user_request)
        return any(token in normalized for token in {"table", "tabela", "tabelas"})

    def _should_list_measures(self, user_request: str) -> bool:
        normalized = self._normalize(user_request)
        return any(
            token in normalized
            for token in {"measure", "measures", "medida", "medidas", "custo", "prato"}
        )

    def _should_summarize_model(self, user_request: str) -> bool:
        normalized = self._normalize(user_request)
        return any(
            token in normalized
            for token in {
                "relatorio",
                "report",
                "aberto",
                "resumo",
                "modelo semantico",
                "semantic model",
            }
        )

    def _should_list_columns(self, user_request: str) -> bool:
        normalized = self._normalize(user_request)
        return any(
            token in normalized
            for token in {"column", "columns", "coluna", "colunas", "campo", "campos"}
        )

    def _should_get_measure_definitions(self, user_request: str) -> bool:
        normalized = self._normalize(user_request)
        return any(
            token in normalized
            for token in {
                "definicao",
                "definicoes",
                "formula",
                "formulas",
                "expressao",
                "expression",
                "dax",
                "calculo",
                "calculos",
                "como foi criada",
                "como foi feito",
                "me mostre",
                "mostre",
                "mostra",
            }
        )

    def _matching_table_names(self, tables: Any, user_request: str) -> list[str]:
        if not isinstance(tables, list):
            return []

        tokens = set(self._search_tokens(user_request))
        named_tables = [
            table
            for table in tables
            if isinstance(table, dict) and isinstance(table.get("name"), str)
        ]
        exact_or_partial = [
            table["name"]
            for table in named_tables
            if self._normalize(table["name"]) in self._normalize(user_request)
            or any(token in self._normalize(table["name"]) for token in tokens)
        ]
        if exact_or_partial:
            return list(dict.fromkeys(exact_or_partial))

        return [table["name"] for table in named_tables[:1]]

    def _matching_measures(
        self,
        measures: Any,
        user_request: str,
    ) -> list[dict[str, Any]]:
        if not isinstance(measures, list):
            return []

        tokens = self._search_tokens(user_request)
        if not tokens:
            return []

        exact_phrase = self._quoted_or_after_measure_phrase(user_request)
        if exact_phrase:
            normalized_exact = self._normalize(exact_phrase)
            exact_matches = [
                measure
                for measure in measures
                if isinstance(measure, dict)
                and isinstance(measure.get("name"), str)
                and normalized_exact in self._normalize(measure["name"])
            ]
            if exact_matches:
                return exact_matches

        candidates = [
            measure
            for measure in measures
            if isinstance(measure, dict)
            and isinstance(measure.get("name"), str)
            and all(token in self._measure_search_text(measure) for token in tokens)
        ]
        if not candidates:
            candidates = [
                measure
                for measure in measures
                if isinstance(measure, dict)
                and isinstance(measure.get("name"), str)
                and any(token in self._measure_search_text(measure) for token in tokens)
            ]

        return sorted(
            candidates,
            key=lambda measure: (
                "(kpi)" in self._normalize(measure["name"]),
                len(measure["name"]),
            ),
        )

    def _best_measure_match(
        self,
        measures: list[dict[str, Any]],
        user_request: str,
    ) -> dict[str, Any] | None:
        if not measures:
            return None

        normalized_request = self._normalize(user_request)
        ranked = sorted(
            measures,
            key=lambda measure: (
                not self._normalize(str(measure.get("name", ""))) in normalized_request,
                "filtro 2" in self._normalize(str(measure.get("name", ""))),
                len(str(measure.get("name", ""))),
            ),
        )
        return ranked[0]

    def _should_execute_measure_query(
        self,
        request: SpecialistExecutionRequest,
    ) -> bool:
        return (
            request.enriched_request.understanding.task_type == TaskType.MEASURE_VALUE_QUERY
            or self._is_ranking_query(request.enriched_request.original_request)
        )

    def _is_ranking_query(self, user_request: str) -> bool:
        normalized = self._normalize(user_request)
        return any(
            token in normalized
            for token in {"mais", "maior", "top", "ranking", "lider", "lidera"}
        )

    def _ranking_dimension(self, user_request: str) -> dict[str, str] | None:
        normalized = self._normalize(user_request)
        dimensions = (
            {
                "keyword": "liner",
                "entity_type": "liner",
                "table_name": "comercial casal_responsaveis",
                "column_name": "liner",
            },
            {
                "keyword": "closer",
                "entity_type": "closer",
                "table_name": "comercial casal_responsaveis",
                "column_name": "closer",
            },
            {
                "keyword": "captador",
                "entity_type": "captador",
                "table_name": "comercial casal_responsaveis",
                "column_name": "captador",
            },
            {
                "keyword": "promotor",
                "entity_type": "promotor",
                "table_name": "comercial casal_responsaveis",
                "column_name": "promotor",
            },
        )
        for dimension in dimensions:
            if dimension["keyword"] in normalized:
                return dimension
        return None

    def _build_ranking_validation_query(
        self,
        *,
        user_request: str,
        measure_name: str,
        table_name: str,
        column_name: str,
        entity_type: str,
    ) -> str:
        entity_name = self._extract_entity_name(user_request, entity_type)
        column_ref = f"'{table_name}'[{column_name}]"
        escaped_entity_name = self._escape_dax_string(entity_name or "")

        return f"""
EVALUATE
VAR SummaryBase =
    FILTER(
        SUMMARIZECOLUMNS(
            {column_ref},
            "MetricValue", [{measure_name}]
        ),
        NOT ISBLANK({column_ref}) && NOT ISBLANK([MetricValue])
    )
VAR Ranked =
    ADDCOLUMNS(
        SummaryBase,
        "MetricRank", RANKX(SummaryBase, [MetricValue],, DESC, Dense)
    )
VAR TopEntity =
    TOPN(1, Ranked, [MetricValue], DESC, {column_ref}, ASC)
VAR SelectedEntity =
    FILTER(
        Ranked,
        UPPER(TRIM({column_ref})) = "{escaped_entity_name}"
    )
RETURN
SELECTCOLUMNS(
    SelectedEntity,
    "EntityType", "{entity_type}",
    "EntityName", {column_ref},
    "MeasureName", "{measure_name}",
    "MetricValue", [MetricValue],
    "MetricRank", [MetricRank],
    "TopEntityName", MAXX(TopEntity, {column_ref}),
    "TopMetricValue", MAXX(TopEntity, [MetricValue]),
    "IsTopEntity", IF([MetricRank] = 1, TRUE(), FALSE())
)
""".strip()

    def _extract_entity_name(self, user_request: str, entity_type: str) -> str | None:
        normalized = self._normalize(user_request)
        pattern = re.compile(
            rf"se\s+o?\s*(.+?)\s+\S+\s+o\s+{re.escape(entity_type)}",
            re.IGNORECASE,
        )
        match = pattern.search(normalized)
        if match:
            return match.group(1).strip(" ?.!:,;").upper()

        fallback = re.compile(
            rf"o?\s*(.+?)\s+\S+\s+o\s+{re.escape(entity_type)}",
            re.IGNORECASE,
        )
        match = fallback.search(normalized)
        if match:
            return match.group(1).strip(" ?.!:,;").upper()
        return None

    def _escape_dax_string(self, value: str) -> str:
        return value.replace('"', '""').upper().strip()

    def _extract_dax_rows(self, response: McpToolCallResponse) -> list[dict[str, Any]]:
        csv_text = self._extract_csv_text(response)
        if not csv_text:
            return []
        reader = csv.DictReader(io.StringIO(csv_text))
        return [dict(row) for row in reader]

    def _extract_csv_text(self, response: McpToolCallResponse) -> str | None:
        raw_content = response.raw_result.get("content")
        if isinstance(raw_content, list):
            for item in raw_content:
                if not isinstance(item, dict):
                    continue
                resource = item.get("resource")
                if isinstance(resource, dict) and isinstance(resource.get("text"), str):
                    return resource["text"]
        for content in response.content:
            if isinstance(content, str) and "," in content and "\n" in content:
                return content
        return None

    def _build_ranking_analysis(
        self,
        rows: list[dict[str, Any]],
        measure_name: str,
    ) -> dict[str, Any] | None:
        if not rows:
            return None

        row = self._normalize_row_keys(rows[0])
        entity_name = row.get("EntityName")
        top_entity_name = row.get("TopEntityName")
        if not entity_name or not top_entity_name:
            return None

        return {
            "entity_type": row.get("EntityType"),
            "entity_name": entity_name,
            "measure_name": row.get("MeasureName") or measure_name,
            "entity_value": row.get("MetricValue"),
            "entity_rank": self._parse_int(row.get("MetricRank")),
            "top_entity_name": top_entity_name,
            "top_entity_value": row.get("TopMetricValue"),
            "is_top_entity": self._parse_bool(row.get("IsTopEntity")),
        }

    def _normalize_row_keys(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in row.items():
            clean_key = str(key).strip().strip("[]")
            normalized[clean_key] = value
        return normalized

    def _parse_int(self, value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(str(value))
        except ValueError:
            return None

    def _parse_bool(self, value: Any) -> bool | None:
        if value is None:
            return None
        normalized = self._normalize(str(value))
        if normalized in {"true", "1"}:
            return True
        if normalized in {"false", "0"}:
            return False
        return None

    def _measure_search_text(self, measure: dict[str, Any]) -> str:
        values = [
            measure.get("name"),
            measure.get("description"),
            measure.get("displayFolder"),
            measure.get("tableName"),
        ]
        return " ".join(self._normalize(str(value)) for value in values if value)

    def _quoted_or_after_measure_phrase(self, user_request: str) -> str | None:
        quoted = re.search(r"['\"]([^'\"]+)['\"]", user_request)
        if quoted:
            return quoted.group(1).strip()

        normalized = self._normalize(user_request)
        for marker in ("medida ", "measure "):
            index = normalized.find(marker)
            if index >= 0:
                phrase = user_request[index + len(marker) :].splitlines()[0].strip(" ?.!:")
                if phrase:
                    return phrase
        return None

    def _flatten_column_payload(self, payload: Any) -> Any:
        if not isinstance(payload, list):
            return payload

        flattened: list[dict[str, Any]] = []
        for item in payload:
            if (
                isinstance(item, dict)
                and isinstance(item.get("columns"), list)
                and all(isinstance(column, dict) for column in item["columns"])
            ):
                flattened.extend(item["columns"])
            elif isinstance(item, dict):
                flattened.append(item)
        return flattened

    def _search_tokens(self, user_request: str) -> list[str]:
        stopwords = {
            "a",
            "as",
            "o",
            "os",
            "de",
            "da",
            "das",
            "do",
            "dos",
            "e",
            "em",
            "me",
            "meu",
            "minha",
            "minhas",
            "qual",
            "quais",
            "que",
            "sao",
            "são",
            "tem",
            "todas",
            "todos",
            "liste",
            "listar",
            "mostre",
            "mostrar",
            "definicao",
            "definicoes",
            "formula",
            "formulas",
            "expressao",
            "dax",
            "medida",
            "medidas",
            "measure",
            "measures",
            "falam",
            "fala",
            "sobre",
            "por",
            "pra",
            "favor",
            "mim",
            "com",
            "verifica",
            "verifique",
            "valida",
            "validar",
            "mais",
            "maior",
            "top",
            "ranking",
            "lider",
            "lidera",
            "liner",
            "closer",
            "captador",
            "promotor",
            "modelo",
            "relatorio",
            "power",
            "bi",
            "prepare",
            "safe",
            "semantic",
            "model",
            "response",
            "enriched",
            "request",
            "original",
            "user",
            "intent",
            "handle",
            "task",
            "type",
            "requested",
            "action",
            "inspect",
            "constraints",
            "retrieved",
            "local",
            "context",
        }
        normalized = self._normalize(user_request)
        dimension = self._ranking_dimension(user_request)
        if dimension:
            entity_name = self._extract_entity_name(user_request, dimension["entity_type"])
            if entity_name:
                for token in re.findall(r"[a-z0-9_]+", self._normalize(entity_name)):
                    normalized = normalized.replace(token, " ")
        tokens = re.findall(r"[a-z0-9_]+", normalized)
        return [
            token
            for token in tokens
            if len(token) >= 3 and token not in stopwords
        ][:8]

    def _normalize(self, value: str) -> str:
        decomposed = unicodedata.normalize("NFD", value)
        return "".join(
            char.lower()
            for char in decomposed
            if unicodedata.category(char) != "Mn"
        )

    def _missing_server_result(
        self,
        request: SpecialistExecutionRequest,
        started_at: float,
    ) -> SpecialistExecutionResult:
        duration_ms = (perf_counter() - started_at) * 1000
        return SpecialistExecutionResult(
            mcp_name=self.name,
            target=self.target,
            status=ResultStatus.ERROR,
            summary="Power BI MCP server was not found in the local catalog.",
            structured_data=None,
            sources_used=self._sources(request),
            trace=["Power BI MCP catalog lookup failed."],
            errors=["MCP server not found: power_bi"],
            warnings=[],
            duration_ms=duration_ms,
            debug={"server_name": self.name},
        )

    def _summary(self, response: McpToolCallResponse) -> str:
        if response.is_error:
            return "Power BI MCP returned an error."
        if response.content:
            return response.content[0][:500]
        return "Power BI MCP produced a semantic-model response."

    def _structured_data(self, response: McpToolCallResponse) -> dict[str, Any] | list[Any] | None:
        if response.structured_content is not None:
            return response.structured_content
        if response.content:
            return {"content": response.content}
        return None

    def _errors(self, response: McpToolCallResponse) -> list[str]:
        if response.content:
            return response.content
        return ["Power BI MCP tool call failed."]

    def _sources(self, request: SpecialistExecutionRequest) -> list[str]:
        return list(
            dict.fromkeys(
                item.source_path
                for item in request.enriched_request.retrieved_context.items
            )
        )

    def _warnings(self, request: SpecialistExecutionRequest) -> list[str]:
        warnings = list(request.policy_decision.warnings) if request.policy_decision else []
        if not request.enriched_request.retrieved_context.items:
            warnings.append("No local context item was retrieved before Power BI execution.")
        return warnings
