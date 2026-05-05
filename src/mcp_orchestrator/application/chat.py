from __future__ import annotations

import json
from typing import Any

import httpx

from mcp_orchestrator.domain.models import ChatResponse, NormalizedResponse, UserRequest
from mcp_orchestrator.application.power_bi_measures import (
    find_matching_measure,
    extract_date_filter_from_query,
)


class ChatAnswerService:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def compose(self, request: UserRequest, orchestration: NormalizedResponse) -> ChatResponse:
        message = self._openai_message(request, orchestration) if self.api_key else None
        return ChatResponse(
            message=message or self._fallback_message(request, orchestration),
            orchestration=orchestration,
            confirmation_id=orchestration.confirmation_id,
            sources_used=orchestration.sources_used,
            next_actions=orchestration.next_actions,
        )

    def _openai_message(
        self,
        request: UserRequest,
        orchestration: NormalizedResponse,
    ) -> str | None:
        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "developer",
                    "content": (
                        "You are the chat layer for an MCP orchestrator used by BI analysts. "
                        "Answer in Portuguese, be concise, and do not invent data. "
                        "Use only the orchestration result, structured data, errors, warnings, "
                        "sources, and next actions supplied by the backend. "
                        "When a confirmation_id exists, explain that read-only execution can be confirmed."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "user_message": request.message,
                            "domain_hint": request.domain_hint,
                            "orchestration": orchestration.model_dump(mode="json"),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        try:
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
            return self._extract_output_text(response.json())
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return None

    def _extract_output_text(self, payload: dict[str, Any]) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

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
                if isinstance(content_item, dict) and isinstance(content_item.get("text"), str):
                    parts.append(content_item["text"])

        text = "".join(parts).strip()
        if not text:
            raise ValueError("OpenAI response did not include output text.")
        return text

    def _fallback_message(self, request: UserRequest, orchestration: NormalizedResponse) -> str:
        # Try to handle measure value query first
        value_query_message = self._measure_value_query_message(request, orchestration)
        if value_query_message:
            return value_query_message
        
        power_bi_message = self._power_bi_message(request, orchestration)
        if power_bi_message:
            return power_bi_message

        lines = [orchestration.summary]
        if orchestration.errors:
            lines.append(f"Erros: {'; '.join(orchestration.errors[:2])}")
        if orchestration.warnings:
            lines.append(f"Avisos: {'; '.join(orchestration.warnings[:2])}")
        if orchestration.confirmation_id:
            lines.append(
                f"Para executar leitura somente leitura, confirme o ID {orchestration.confirmation_id}."
            )
        if orchestration.sources_used:
            lines.append(f"Fontes usadas: {', '.join(orchestration.sources_used[:3])}")
        return "\n".join(lines)
    
    def _measure_value_query_message(
        self,
        request: UserRequest,
        orchestration: NormalizedResponse,
    ) -> str | None:
        """
        Format response for measure value queries.
        Tries to extract actual measure values from Power BI execution results.
        """
        power_bi_data = None
        if isinstance(orchestration.structured_data, dict):
            power_bi_data = orchestration.structured_data.get("power_bi")
        if not isinstance(power_bi_data, dict):
            return None
        
        # Check if we have DAX query results
        dax_results = power_bi_data.get("dax_query_results")
        if not dax_results:
            # Try to generate a helpful message if we have the measure info
            return self._generate_value_query_preview(request, power_bi_data)
        
        # Format the actual results
        return self._format_dax_results(request, dax_results, power_bi_data)
    
    def _generate_value_query_preview(self, request: UserRequest, power_bi_data: dict[str, Any]) -> str | None:
        """
        Generate a preview/suggestion message for value queries,
        indicating which measure was identified and what would be queried.
        """
        # Try to match the measure from user request
        measure = find_matching_measure(request.message)
        date_filter = extract_date_filter_from_query(request.message)
        
        if not measure:
            return None
        
        lines = [f"Identificada medida: {measure.display_name}"]
        
        if date_filter:
            date_parts = []
            if date_filter.get("month"):
                months = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
                         "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
                month_name = months[date_filter["month"] - 1]
                date_parts.append(month_name)
            if date_filter.get("year"):
                date_parts.append(f"de {date_filter['year']}")
            if date_filter.get("quarter"):
                date_parts.append(f"Q{date_filter['quarter']}")
            
            if date_parts:
                lines.append(f"Período: {' '.join(date_parts)}")
        
        lines.append(f"Descrição: {measure.description}")
        
        connection = power_bi_data.get("connection")
        if isinstance(connection, dict):
            process = connection.get("parentProcessName", "Power BI")
            port = connection.get("port")
            port_str = f" (porta {port})" if port else ""
            lines.append(f"Conexão: {process}{port_str}")
        
        lines.append("Executando query para obter valor...")
        return "\n".join(lines)
    
    def _format_dax_results(
        self,
        request: UserRequest,
        dax_results: Any,
        power_bi_data: dict[str, Any],
    ) -> str | None:
        """
        Format the results from a DAX query execution into a readable message.
        """
        measure = find_matching_measure(request.message)
        date_filter = extract_date_filter_from_query(request.message)
        
        if not isinstance(dax_results, dict):
            return None
        
        # Extract value from results
        value = dax_results.get("value") or dax_results.get("result")
        if value is None:
            rows = dax_results.get("rows", [])
            if rows and isinstance(rows, list) and len(rows) > 0:
                # Try to extract first row's value
                first_row = rows[0]
                if isinstance(first_row, dict):
                    value = first_row.get("value") or first_row.get("Valor")
        
        if value is None:
            return None
        
        # Format the friendly message
        lines = []
        
        # Build context string
        measure_name = measure.display_name if measure else "Medida"
        if date_filter:
            date_parts = []
            if date_filter.get("month"):
                months = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
                         "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
                month_name = months[date_filter["month"] - 1]
                date_parts.append(month_name)
            if date_filter.get("year"):
                date_parts.append(f"de {date_filter['year']}")
            period = f" em {' '.join(date_parts)}" if date_parts else ""
        else:
            period = ""
        
        # Format based on value type
        if isinstance(value, (int, float)):
            formatted_value = f"{value:,.0f}".replace(",", ".")
        else:
            formatted_value = str(value)
        
        lines.append(f"**{measure_name}{period}**: {formatted_value}")
        
        # Add additional context
        if isinstance(dax_results, dict) and dax_results.get("query"):
            lines.append(f"(DAX Query executed successfully)")
        
        connection = power_bi_data.get("connection")
        if isinstance(connection, dict):
            title = connection.get("parentWindowTitle")
            if title:
                lines.append(f"Relatório: {title}")
        
        return "\n".join(lines)

    def _power_bi_message(
        self,
        request: UserRequest,
        orchestration: NormalizedResponse,
    ) -> str | None:
        power_bi_data = None
        if isinstance(orchestration.structured_data, dict):
            power_bi_data = orchestration.structured_data.get("power_bi")
        if not isinstance(power_bi_data, dict):
            return None

        connection = power_bi_data.get("connection")
        if not isinstance(connection, dict):
            return None

        title = connection.get("parentWindowTitle") or "sem titulo"
        process = connection.get("parentProcessName") or "Power BI"
        port = connection.get("port")
        tables = power_bi_data.get("tables")
        measures = power_bi_data.get("measures")
        matching_measures = power_bi_data.get("matching_measures")
        measure_definitions = power_bi_data.get("measure_definitions")
        columns = power_bi_data.get("columns")

        lines = [
            f"Relatorio Power BI aberto: {title}.",
            f"Instancia: {process}" + (f" na porta {port}." if port else "."),
        ]
        if isinstance(tables, list):
            table_names = [
                str(table.get("name"))
                for table in tables
                if isinstance(table, dict) and table.get("name")
            ]
            if table_names:
                lines.append(f"Tabelas encontradas ({len(table_names)}): {', '.join(table_names[:6])}.")

        column_lines = self._format_columns(columns)
        if column_lines:
            lines.extend(column_lines)

        definition_lines = self._format_measure_definitions(measure_definitions)
        if definition_lines:
            lines.extend(definition_lines)
        elif isinstance(matching_measures, list) and matching_measures:
            label = self._measure_label(request.message)
            names = self._names(matching_measures)
            lines.append(
                f"{label} ({len(names)}): {self._limited_join(names, limit=25)}."
            )
        elif isinstance(measures, list):
            names = self._names(measures)
            if self._asks_for_measure_names(request.message) and names:
                lines.append(
                    f"Medidas encontradas ({len(names)}): {self._limited_join(names, limit=30)}."
                )
            else:
                lines.append(f"Medidas encontradas: {len(measures)}.")
        if orchestration.sources_used:
            lines.append(f"Fonte de regra usada: {orchestration.sources_used[0]}.")
        return "\n".join(lines)

    def _format_columns(self, columns: Any) -> list[str]:
        if not isinstance(columns, dict) or not columns:
            return []

        lines: list[str] = []
        for table_name, table_columns in list(columns.items())[:3]:
            if not isinstance(table_columns, list):
                lines.append(f"Colunas da tabela {table_name}: dados retornados pelo MCP.")
                continue
            names = self._names(self._flatten_column_items(table_columns))
            if names:
                lines.append(
                    f"Colunas da tabela {table_name} ({len(names)}): "
                    f"{self._limited_join(names, limit=40)}."
                )
        return lines

    def _format_measure_definitions(self, definitions: Any) -> list[str]:
        if not isinstance(definitions, list) or not definitions:
            return []

        lines = ["Definicoes de medidas encontradas:"]
        for measure in definitions[:5]:
            if not isinstance(measure, dict):
                continue
            name = self._clean_text(measure.get("name") or "medida sem nome")
            expression = (
                measure.get("expression")
                or measure.get("formula")
                or measure.get("dax")
                or measure.get("definition")
            )
            table_name = self._clean_text(measure.get("tableName")) if measure.get("tableName") else None
            prefix = f"- {name}" + (f" ({table_name})" if table_name else "")
            if expression:
                lines.append(f"{prefix}: {self._clean_text(str(expression))}")
            else:
                lines.append(prefix)
        return lines

    def _names(self, items: list[Any]) -> list[str]:
        names = [
            self._clean_text(str(item.get("name")))
            for item in items
            if isinstance(item, dict) and item.get("name")
        ]
        return list(dict.fromkeys(names))

    def _flatten_column_items(self, items: list[Any]) -> list[Any]:
        flattened: list[Any] = []
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("columns"), list):
                flattened.extend(item["columns"])
            else:
                flattened.append(item)
        return flattened

    def _limited_join(self, names: list[str], *, limit: int) -> str:
        visible = names[:limit]
        suffix = f", e mais {len(names) - limit}" if len(names) > limit else ""
        return ", ".join(visible) + suffix

    def _asks_for_measure_names(self, message: str) -> bool:
        normalized = message.lower()
        return any(token in normalized for token in {"medida", "medidas", "measure", "measures"})

    def _measure_label(self, message: str) -> str:
        normalized = message.lower()
        if "falam" in normalized or "sobre" in normalized:
            return "Medidas relacionadas"
        return "Medidas encontradas"

    def _clean_text(self, value: str) -> str:
        if any(marker in value for marker in ("Ã", "Â", "�")):
            try:
                return value.encode("latin1").decode("utf-8")
            except UnicodeError:
                return value
        return value
