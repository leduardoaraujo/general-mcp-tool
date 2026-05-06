from __future__ import annotations

import json
import csv
import io
import re
import unicodedata
from datetime import UTC, datetime
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
                "execution_trace": response.structured_content.get("execution_trace")
                if isinstance(response.structured_content, dict)
                else None,
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
        execution_trace: list[dict[str, Any]] = []
        local_instances = await caller.call_tool(
            "connection_operations",
            {"request": {"operation": "ListLocalInstances"}},
        )
        operations.append(self._operation_record("connection_operations", local_instances))
        self._append_execution_trace_step(
            execution_trace,
            tool_name="connection_operations",
            arguments={"request": {"operation": "ListLocalInstances"}},
            response=local_instances,
        )
        if local_instances.is_error:
            return self._aggregate_guided_response(
                is_error=True,
                summary="Power BI local instance discovery failed.",
                operations=operations,
                execution_trace=execution_trace,
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
        self._append_execution_trace_step(
            execution_trace,
            tool_name="connection_operations",
            arguments={
                "request": {
                    "operation": "Connect",
                    "connectionString": instance.get("connectionString"),
                }
            },
            response=connect,
        )
        if connect.is_error:
            return self._aggregate_guided_response(
                is_error=True,
                summary="Power BI local instance connection failed.",
                operations=operations,
                connection=instance,
                execution_trace=execution_trace,
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
                {"request": {"operation": "List", "filter": {"maxResults": 2000}}},
            )
            operations.append(self._operation_record("table_operations", tables))
            self._append_execution_trace_step(
                execution_trace,
                tool_name="table_operations",
                arguments={"request": {"operation": "List", "filter": {"maxResults": 2000}}},
                response=tables,
            )
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
                        {"request": {"operation": "List", "filter": {"maxResults": 2000}}},
                    )
                    operations.append(self._operation_record("table_operations", tables))
                    self._append_execution_trace_step(
                        execution_trace,
                        tool_name="table_operations",
                        arguments={"request": {"operation": "List", "filter": {"maxResults": 2000}}},
                        response=tables,
                    )
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
                self._append_execution_trace_step(
                    execution_trace,
                    tool_name="column_operations",
                    arguments={
                        "request": {
                            "operation": "List",
                            "filter": {"tableNames": [table_name], "maxResults": 300},
                        }
                    },
                    response=columns,
                )
                columns_by_table[table_name] = self._flatten_column_payload(
                    self._payload_data(columns)
                )
            if columns_by_table:
                guided_data["columns"] = columns_by_table

        should_execute_measure_query = self._should_execute_measure_query(request)
        intent_detected = "comparacao" if self._is_comparison_request(original_user_request) else (
            "ranking" if self._is_ranking_query(original_user_request) else (
                "valor" if self._is_measure_value_request(original_user_request) else "metadata"
            )
        )
        guided_data["intent_detected"] = intent_detected

        if should_execute_measure_query or self._should_list_measures(original_user_request) or summarize_model:
            measures = await caller.call_tool(
                "measure_operations",
                {"request": {"operation": "List", "filter": {"maxResults": 2000}}},
            )
            operations.append(self._operation_record("measure_operations", measures))
            self._append_execution_trace_step(
                execution_trace,
                tool_name="measure_operations",
                arguments={"request": {"operation": "List", "filter": {"maxResults": 2000}}},
                response=measures,
            )
            measure_list = self._payload_data(measures)
            guided_data["measures"] = measure_list

            matches = self._matching_measures(measure_list, original_user_request)
            if matches and should_execute_measure_query:
                guided_data["matching_measures"] = matches
                query_result = await self._execute_measure_query(
                    caller,
                    original_user_request,
                    matches,
                    measure_list if isinstance(measure_list, list) else [],
                    request.enriched_request.metadata.get("analysis_context")
                    if isinstance(request.enriched_request.metadata, dict)
                    else None,
                )
                if query_result is not None:
                    operations.append(query_result["operation"])
                    guided_data.update(query_result["guided_data"])
                    execution_trace.append(query_result["execution_trace"])
                    guided_data["dax_executed"] = True
            elif should_execute_measure_query:
                guided_data["dax_executed"] = False
                guided_data["reason_if_not_executed"] = "Nenhuma medida compativel foi encontrada para a pergunta."

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
                self._append_execution_trace_step(
                    execution_trace,
                    tool_name="measure_operations",
                    arguments={
                        "request": {
                            "operation": "Get",
                            "references": [{"name": measure["name"]} for measure in matches[:5]],
                        }
                    },
                    response=measure_definitions,
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
            self._append_execution_trace_step(
                execution_trace,
                tool_name="model_operations",
                arguments={"request": {"operation": "GetStats"}},
                response=stats,
            )
            guided_data["model_stats"] = self._payload_data(stats)
        elif should_execute_measure_query and "dax_executed" not in guided_data:
            guided_data["dax_executed"] = False
            guided_data["reason_if_not_executed"] = "Execucao analitica nao foi disparada."

        return self._aggregate_guided_response(
            is_error=any(record["is_error"] for record in operations),
            summary=self._guided_summary(guided_data),
            operations=operations,
            connection=instance,
            guided_data=guided_data,
            execution_trace=execution_trace,
        )

    def _aggregate_guided_response(
        self,
        *,
        is_error: bool,
        summary: str,
        operations: list[dict[str, Any]],
        connection: dict[str, Any] | None = None,
        guided_data: dict[str, Any] | None = None,
        execution_trace: list[dict[str, Any]] | None = None,
    ) -> McpToolCallResponse:
        structured_content = {
            "summary": summary,
            "connection": connection,
            "operations": operations,
            "execution_trace": execution_trace or [],
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
        all_measures: list[dict[str, Any]],
        analysis_context: Any,
    ) -> dict[str, Any] | None:
        intent = "comparacao" if self._is_comparison_request(user_request) else "valor"
        primary_measure, comparison_measure, comparison_basis = self._resolve_measure_pair(
            user_request=user_request,
            matches=matches,
            all_measures=all_measures,
            analysis_context=analysis_context,
        )
        if not primary_measure:
            return None

        measure_name = primary_measure.get("name")
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
        elif intent == "comparacao" and comparison_measure:
            comparison_name = comparison_measure.get("name")
            if not isinstance(comparison_name, str):
                comparison_name = None
            if comparison_name:
                dax_query = self._build_comparison_query(
                    primary_measure_name=measure_name,
                    comparison_measure_name=comparison_name,
                    comparison_basis=comparison_basis,
                )
            else:
                dax_query = f'EVALUATE ROW("MetricValue", [{measure_name}])'
        else:
            dax_query = f'EVALUATE ROW("MetricValue", [{measure_name}])'

        started_at = datetime.now(UTC)
        started_perf = perf_counter()
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
        duration_ms = round((perf_counter() - started_perf) * 1000, 3)
        operation = self._operation_record("dax_query_operations", dax_response)
        rows = self._extract_dax_rows(dax_response)
        scalar_value = self._extract_scalar_value(rows)
        guided_data: dict[str, Any] = {
            "dax_query_results": {
                "query": dax_query,
                "rows": rows,
                "measure_name": measure_name,
                "value": scalar_value,
                "comparison_metric_name": comparison_measure.get("name") if comparison_measure else None,
                "comparison_basis": comparison_basis,
            }
        }

        ranking_analysis = self._build_ranking_analysis(rows, measure_name)
        if ranking_analysis:
            guided_data["ranking_analysis"] = ranking_analysis

        formatted_value = self._format_numeric_value_for_trace(scalar_value)
        return {
            "operation": operation,
            "guided_data": guided_data,
            "execution_trace": {
                "target_mcp": self.target.value,
                "tool_name": "dax_query_operations",
                "operation": "Execute",
                "started_at": started_at.isoformat(),
                "duration_ms": duration_ms,
                "status": "error" if dax_response.is_error else "success",
                "input": {
                    "query": dax_query,
                    "maxRows": 20,
                    "timeoutSeconds": 120,
                    "matched_measure": measure_name,
                    "comparison_measure": comparison_measure.get("name") if comparison_measure else None,
                },
                "validation": {
                    "intent_detected": intent,
                    "matched_measure_found": bool(measure_name),
                    "ranking_mode": bool(dimension and self._is_ranking_query(user_request)),
                    "comparison_basis": comparison_basis,
                    "raw_value_available": scalar_value is not None,
                },
                "calculation": {
                    "raw_value": scalar_value,
                    "formatted_value": formatted_value,
                    "format_divergence": scalar_value != formatted_value if scalar_value is not None else False,
                },
                "output_summary": self._build_output_summary(rows, scalar_value),
                "output_sample": rows[:10],
                "errors": dax_response.content if dax_response.is_error else [],
                "warnings": [],
            },
        }

    def _build_comparison_query(
        self,
        *,
        primary_measure_name: str,
        comparison_measure_name: str,
        comparison_basis: str,
    ) -> str:
        escaped_basis = comparison_basis.replace('"', '""')
        escaped_comparison = comparison_measure_name.replace('"', '""')
        return f"""
EVALUATE
ROW(
    "MetricValue", [{primary_measure_name}],
    "ComparisonValue", [{comparison_measure_name}],
    "ComparisonMetricName", "{escaped_comparison}",
    "ComparisonBasis", "{escaped_basis}",
    "DeltaValue", [{primary_measure_name}] - [{comparison_measure_name}],
    "DeltaPercent", DIVIDE([{primary_measure_name}] - [{comparison_measure_name}], [{comparison_measure_name}])
)
""".strip()

    def _resolve_measure_pair(
        self,
        *,
        user_request: str,
        matches: list[dict[str, Any]],
        all_measures: list[dict[str, Any]],
        analysis_context: Any,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
        explicit_measure_name = self._extract_explicit_measure_name(user_request)
        if explicit_measure_name:
            strict_primary = self._find_measure_by_explicit_name(all_measures, explicit_measure_name)
            if strict_primary is None:
                # Nunca chutar outra medida quando o usuário especificou explicitamente uma medida.
                return None, None, None
            primary = strict_primary
        else:
            primary = self._best_measure_match(matches, user_request)
        comparison = None
        basis = None
        if not self._is_comparison_request(user_request):
            return primary, comparison, basis

        normalized_request = self._normalize(user_request)
        explicit_meta = [
            item for item in matches
            if isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and "meta" in self._normalize(item["name"])
        ]
        if explicit_meta:
            comparison = self._best_measure_match(explicit_meta, user_request)
            basis = "explicit_meta"

        if primary and comparison and primary == comparison:
            primary = self._infer_primary_from_family(
                all_measures=all_measures,
                comparison_measure=comparison,
                analysis_context=analysis_context,
            )
            if primary is None:
                primary = self._default_primary_for_request(all_measures, normalized_request)

        if primary is None:
            primary = self._primary_from_context(all_measures, analysis_context)
        if primary is None:
            primary = self._default_primary_for_request(all_measures, normalized_request)

        if comparison is None and primary is not None:
            comparison = self._comparison_from_family(all_measures, primary, normalized_request)
            if comparison is not None:
                basis = "inferred_family"

        if comparison is None:
            comparison = self._comparison_from_context(all_measures, analysis_context)
            if comparison is not None and basis is None:
                basis = "explicit_meta"

        return primary, comparison, basis

    def _primary_from_context(self, all_measures: list[dict[str, Any]], analysis_context: Any) -> dict[str, Any] | None:
        if not isinstance(analysis_context, dict):
            return None
        name = analysis_context.get("last_metric_name")
        return self._find_measure_by_name(all_measures, name)

    def _comparison_from_context(self, all_measures: list[dict[str, Any]], analysis_context: Any) -> dict[str, Any] | None:
        if not isinstance(analysis_context, dict):
            return None
        name = analysis_context.get("last_comparison_metric_name")
        return self._find_measure_by_name(all_measures, name)

    def _default_primary_for_request(self, all_measures: list[dict[str, Any]], normalized_request: str) -> dict[str, Any] | None:
        priority = ("vgv vendido", "propostas vgv", "propostas")
        for wanted in priority:
            for measure in all_measures:
                if isinstance(measure, dict) and isinstance(measure.get("name"), str):
                    if wanted in self._normalize(measure["name"]) and (
                        "vgv" in normalized_request or wanted == "propostas"
                    ):
                        return measure
        return None

    def _comparison_from_family(
        self,
        all_measures: list[dict[str, Any]],
        primary_measure: dict[str, Any],
        normalized_request: str,
    ) -> dict[str, Any] | None:
        primary_name = str(primary_measure.get("name") or "")
        family_tokens = [token for token in re.findall(r"[a-z0-9_]+", self._normalize(primary_name)) if len(token) > 2]
        candidates: list[dict[str, Any]] = []
        for measure in all_measures:
            if not isinstance(measure, dict) or not isinstance(measure.get("name"), str):
                continue
            normalized_name = self._normalize(measure["name"])
            if "meta" not in normalized_name:
                continue
            if any(token in normalized_name for token in family_tokens) or "vgv" in normalized_request and "vgv" in normalized_name:
                candidates.append(measure)
        return self._best_measure_match(candidates, primary_name) if candidates else None

    def _infer_primary_from_family(
        self,
        *,
        all_measures: list[dict[str, Any]],
        comparison_measure: dict[str, Any],
        analysis_context: Any,
    ) -> dict[str, Any] | None:
        context_primary = self._primary_from_context(all_measures, analysis_context)
        if context_primary is not None:
            return context_primary
        comparison_name = self._normalize(str(comparison_measure.get("name") or ""))
        tokens = [token for token in re.findall(r"[a-z0-9_]+", comparison_name) if token not in {"meta", "mes", "dia"}]
        for measure in all_measures:
            if not isinstance(measure, dict) or not isinstance(measure.get("name"), str):
                continue
            normalized_name = self._normalize(measure["name"])
            if "meta" in normalized_name:
                continue
            if any(token in normalized_name for token in tokens):
                return measure
        return None

    def _find_measure_by_name(self, all_measures: list[dict[str, Any]], name: Any) -> dict[str, Any] | None:
        if not isinstance(name, str) or not name.strip():
            return None
        normalized_target = self._normalize(name)
        for measure in all_measures:
            if isinstance(measure, dict) and isinstance(measure.get("name"), str):
                if self._normalize(measure["name"]) == normalized_target:
                    return measure
        return None

    def _append_execution_trace_step(
        self,
        execution_trace: list[dict[str, Any]],
        *,
        tool_name: str,
        arguments: dict[str, Any],
        response: McpToolCallResponse,
    ) -> None:
        payload = self._payload(response)
        output_data = self._payload_data(response)
        output_rows = output_data if isinstance(output_data, list) else []
        execution_trace.append(
            {
                "target_mcp": self.target.value,
                "tool_name": tool_name,
                "operation": self._operation_name(arguments),
                "started_at": datetime.now(UTC).isoformat(),
                "duration_ms": 0.0,
                "status": "error" if response.is_error else "success",
                "input": arguments,
                "validation": {},
                "calculation": {},
                "output_summary": self._generic_output_summary(payload, output_data),
                "output_sample": output_rows[:10] if isinstance(output_rows, list) else [],
                "errors": response.content if response.is_error else [],
                "warnings": [],
            }
        )

    def _operation_name(self, arguments: dict[str, Any]) -> str:
        request = arguments.get("request")
        if isinstance(request, dict):
            operation = request.get("operation")
            if isinstance(operation, str):
                return operation
        return "unknown"

    def _generic_output_summary(self, payload: Any, output_data: Any) -> dict[str, Any]:
        row_count = len(output_data) if isinstance(output_data, list) else (1 if output_data is not None else 0)
        first_row = output_data[0] if isinstance(output_data, list) and output_data and isinstance(output_data[0], dict) else None
        return {
            "row_count": row_count,
            "primary_value": self._extract_first_row_value(first_row) if first_row else None,
            "keys": list(first_row.keys())[:8] if first_row else [],
            "payload_has_results": isinstance(payload, dict) and ("results" in payload or "data" in payload),
        }

    def _build_output_summary(self, rows: list[dict[str, Any]], scalar_value: Any) -> dict[str, Any]:
        first_row = rows[0] if rows and isinstance(rows[0], dict) else None
        return {
            "row_count": len(rows),
            "primary_value": scalar_value,
            "keys": list(first_row.keys())[:8] if first_row else [],
        }

    def _extract_first_row_value(self, row: dict[str, Any]) -> Any:
        if not isinstance(row, dict):
            return None
        for key in ("value", "Value", "Valor", "MetricValue", "[MetricValue]"):
            if key in row and row.get(key) not in (None, ""):
                return row.get(key)
        for row_value in row.values():
            if row_value not in (None, ""):
                return row_value
        return None

    def _format_numeric_value_for_trace(self, value: Any) -> str | Any:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return self._format_pt_br_number(float(value), decimals=0 if float(value).is_integer() else 2)
        if isinstance(value, str):
            parsed = self._parse_number_like(value)
            if parsed is None:
                return value
            return self._format_pt_br_number(parsed, decimals=0 if parsed.is_integer() else 2)
        return value

    def _parse_number_like(self, text: str) -> float | None:
        candidate = str(text).replace(" ", "")
        if not re.fullmatch(r"[-+]?[0-9][0-9.,]*", candidate):
            return None
        if "," in candidate and "." in candidate:
            normalized = candidate.replace(".", "").replace(",", ".") if candidate.rfind(",") > candidate.rfind(".") else candidate.replace(",", "")
        elif "," in candidate:
            if candidate.count(",") > 1:
                normalized = candidate.replace(",", "")
            else:
                normalized = candidate.replace(",", ".")
        elif "." in candidate and candidate.count(".") > 1:
            normalized = candidate.replace(".", "")
        else:
            normalized = candidate
        try:
            return float(normalized)
        except ValueError:
            return None

    def _format_pt_br_number(self, value: float, *, decimals: int) -> str:
        formatted = f"{value:,.{decimals}f}"
        return formatted.replace(",", "X").replace(".", ",").replace("X", ".")

    def _extract_scalar_value(self, rows: list[dict[str, Any]]) -> Any:
        if not rows or not isinstance(rows[0], dict):
            return None
        first_row = rows[0]
        preferred_keys = ("value", "Value", "Valor", "MetricValue", "[MetricValue]")
        for key in preferred_keys:
            if key in first_row and first_row.get(key) not in (None, ""):
                return first_row.get(key)
        for _, row_value in first_row.items():
            if row_value not in (None, ""):
                return row_value
        return None

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
                "o que e",
                "oque e",
                "significa",
                "conceito",
                "onde aplico",
                "como aplicar",
                "para que serve",
                "pra que serve",
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
        request_tokens = set(self._search_tokens(user_request))
        ranked = sorted(
            measures,
            key=lambda measure: (
                not self._normalize(str(measure.get("name", ""))) in normalized_request,
                -self._token_overlap_score(str(measure.get("name", "")), request_tokens),
                "filtro 2" in self._normalize(str(measure.get("name", ""))),
                len(str(measure.get("name", ""))),
            ),
        )
        return ranked[0]

    def _should_execute_measure_query(
        self,
        request: SpecialistExecutionRequest,
    ) -> bool:
        user_request = request.enriched_request.original_request
        if self._is_explanatory_request(user_request):
            return False
        return (
            request.enriched_request.understanding.task_type == TaskType.MEASURE_VALUE_QUERY
            or self._is_measure_value_request(user_request)
            or self._is_comparison_request(user_request)
            or self._is_ranking_query(request.enriched_request.original_request)
        )

    def _is_explanatory_request(self, user_request: str) -> bool:
        normalized = self._normalize(user_request)
        return any(
            token in normalized
            for token in {
                "o que e",
                "oque e",
                "significa",
                "conceito",
                "onde aplico",
                "como aplicar",
                "para que serve",
                "pra que serve",
            }
        )

    def _is_measure_value_request(self, user_request: str) -> bool:
        normalized = self._normalize(user_request)
        asks_value = any(
            token in normalized
            for token in {
                "qual o numero",
                "qual numero",
                "numero da",
                "numero de",
                "quanto",
                "valor da",
                "valor de",
                "retorna",
                "resultado",
                "margem",
                "percentual",
                "%",
            }
        )
        references_measure = any(
            token in normalized
            for token in {"medida", "measure", "meta", "vgv", "propostas", "margem", "gop", "%", "percentual"}
        )
        return asks_value and references_measure

    def _is_comparison_request(self, user_request: str) -> bool:
        normalized = self._normalize(user_request)
        asks_comparison = any(
            token in normalized
            for token in {"compar", "versus", " vs ", "meta", "atingimento", "diferenca", "%"}
        )
        references_measure = any(
            token in normalized
            for token in {"vgv", "meta", "medida", "measure", "propostas", "vendido"}
        )
        return asks_comparison and references_measure

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

    def _extract_explicit_measure_name(self, user_request: str) -> str | None:
        phrase = self._quoted_or_after_measure_phrase(user_request)
        if not phrase:
            return None
        phrase = phrase.split(",")[0].strip()
        phrase = re.sub(r"^(de|da|do|das|dos)\s+", "", phrase, flags=re.IGNORECASE)
        cleaned = re.split(
            r"\b(para|pra|com|usando|use|usar|verifica|verificar|valida|validar|por favor|qual|quanto|valor|numero|retorna|resultado)\b",
            phrase,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip(" .,!?:;")
        if not cleaned:
            return None
        token_count = len(re.findall(r"[a-z0-9_]+", self._normalize(cleaned)))
        return cleaned if token_count >= 1 else None

    def _find_measure_by_explicit_name(
        self,
        all_measures: list[dict[str, Any]],
        explicit_name: str,
    ) -> dict[str, Any] | None:
        if not explicit_name:
            return None
        normalized_explicit = self._normalize(explicit_name)
        stop_tokens = {
            "de", "da", "do", "das", "dos", "qual", "quanto", "valor", "numero",
            "retorna", "resultado", "medida", "measure", "usar", "use", "pra", "para", "com",
        }
        explicit_tokens = {
            token
            for token in re.findall(r"[a-z0-9_]+", normalized_explicit)
            if token not in stop_tokens and len(token) >= 2
        }
        for measure in all_measures:
            if not isinstance(measure, dict) or not isinstance(measure.get("name"), str):
                continue
            measure_name = str(measure["name"])
            normalized_name = self._normalize(measure_name)
            if normalized_name == normalized_explicit:
                return measure
        for measure in all_measures:
            if not isinstance(measure, dict) or not isinstance(measure.get("name"), str):
                continue
            normalized_name = self._normalize(str(measure["name"]))
            if normalized_explicit in normalized_name or normalized_name in normalized_explicit:
                return measure
        for measure in all_measures:
            if not isinstance(measure, dict) or not isinstance(measure.get("name"), str):
                continue
            name_tokens = set(re.findall(r"[a-z0-9_]+", self._normalize(str(measure["name"]))))
            if explicit_tokens and explicit_tokens.issubset(name_tokens):
                return measure
        return None

    def _token_overlap_score(self, measure_name: str, request_tokens: set[str]) -> int:
        if not request_tokens:
            return 0
        measure_tokens = set(re.findall(r"[a-z0-9_]+", self._normalize(measure_name)))
        return len(request_tokens & measure_tokens)

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
