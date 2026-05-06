from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from mcp_orchestrator.application.power_bi_measures import extract_date_filter_from_query
from mcp_orchestrator.domain.models import ChatResponse, NormalizedResponse, UserRequest


class ChatAnswerService:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        groq_api_key: str | None = None,
        groq_model: str = "llama-3.1-8b-instant",
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.groq_api_key = groq_api_key
        self.groq_model = groq_model
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.logger = logging.getLogger(__name__)
        self._analysis_context_by_key: dict[str, dict[str, Any]] = {}

    def enrich_request(self, request: UserRequest) -> UserRequest:
        key = self._context_key(request)
        cached = self._analysis_context_by_key.get(key)
        if not cached:
            return request
        metadata = dict(request.metadata)
        metadata.setdefault("analysis_context", cached)
        return request.model_copy(update={"metadata": metadata})

    def compose(self, request: UserRequest, orchestration: NormalizedResponse) -> ChatResponse:
        response_profile = self._response_profile(request)
        fallback_message, presentation = self._fallback_content(request, orchestration, response_profile)
        analytical = self._is_analytical_query(request.message)
        message = None if analytical else self._llm_message(request, orchestration)
        if presentation:
            self._update_analysis_context(request, presentation)
        return ChatResponse(
            message=message or fallback_message,
            orchestration=orchestration,
            confirmation_id=orchestration.confirmation_id,
            sources_used=orchestration.sources_used,
            next_actions=orchestration.next_actions,
            presentation=presentation,
        )

    def _llm_message(self, request: UserRequest, orchestration: NormalizedResponse) -> str | None:
        if self.api_key:
            openai_message = self._openai_message(request, orchestration)
            if openai_message:
                return openai_message
        if self.groq_api_key:
            return self._groq_message(request, orchestration)
        return None

    def _openai_message(self, request: UserRequest, orchestration: NormalizedResponse) -> str | None:
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
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, httpx.HTTPStatusError):
                self.logger.warning(
                    "OpenAI response generation failed with status %s; using local fallback.",
                    exc.response.status_code,
                )
            else:
                self.logger.warning("OpenAI response generation failed; using local fallback.")
            return None

    def _groq_message(self, request: UserRequest, orchestration: NormalizedResponse) -> str | None:
        if not self.groq_api_key:
            return None
        payload = {
            "model": self.groq_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Voce e a camada de chat de um orquestrador MCP para analistas de BI. "
                        "Responda em portugues, seja conciso e nao invente dados. "
                        "Use apenas os dados de orquestracao informados."
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
            "temperature": 0.7,
            "max_completion_tokens": 1024,
            "top_p": 1,
            "stream": False,
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self.transport) as client:
                response = client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.groq_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                body = response.json()
            choices = body.get("choices", [])
            if not isinstance(choices, list) or not choices:
                return None
            message = choices[0].get("message", {})
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str) and content.strip():
                return content.strip()
            return None
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, httpx.HTTPStatusError):
                self.logger.warning(
                    "Groq response generation failed with status %s; using local fallback.",
                    exc.response.status_code,
                )
            else:
                self.logger.warning("Groq response generation failed; using local fallback.")
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

    def _fallback_content(
        self,
        request: UserRequest,
        orchestration: NormalizedResponse,
        response_profile: str,
    ) -> tuple[str, dict[str, Any] | None]:
        value_message, value_presentation = self._measure_value_query_message(
            request,
            orchestration,
            response_profile,
        )
        if value_message:
            return value_message, value_presentation

        power_bi_message, power_bi_presentation = self._power_bi_message(request, orchestration, response_profile)
        if power_bi_message:
            return power_bi_message, power_bi_presentation

        lines = [orchestration.summary]
        if orchestration.errors:
            lines.append(f"Erros: {'; '.join(orchestration.errors[:2])}")
        if orchestration.warnings:
            lines.append(f"Avisos: {'; '.join(orchestration.warnings[:2])}")
        if orchestration.confirmation_id:
            lines.append(
                f"Para executar leitura somente leitura, confirme o ID {orchestration.confirmation_id}."
            )
        return "\n".join(lines), None

    def _measure_value_query_message(
        self,
        request: UserRequest,
        orchestration: NormalizedResponse,
        response_profile: str,
    ) -> tuple[str | None, dict[str, Any] | None]:
        power_bi_data = None
        if isinstance(orchestration.structured_data, dict):
            power_bi_data = orchestration.structured_data.get("power_bi")
        if not isinstance(power_bi_data, dict):
            return None, None

        ranking_message = self._ranking_query_message(power_bi_data)
        if ranking_message:
            return ranking_message, self._ranking_presentation(request, power_bi_data)

        dax_results = power_bi_data.get("dax_query_results")
        if not dax_results:
            if self._asks_for_analytical_value(request.message):
                measure_names = self._names(power_bi_data.get("matching_measures") or [])
                measure_name = measure_names[0] if measure_names else "a medida solicitada"
                message = (
                    f"Nao consegui retornar o valor de {measure_name} porque esta execucao nao trouxe "
                    "resultado de DAX (apenas metadados/listagem). "
                    "Para responder com numero, preciso executar a medida em contexto de filtro."
                )
                presentation = self._base_presentation(
                    intent_type=self._infer_intent_type(request.message, has_comparison=False),
                    response_profile=response_profile,
                    measure_name=measure_name,
                    period_label=self._period_label_from_request(request.message),
                    report_context=self._report_context(power_bi_data),
                )
                presentation["insight_summary"] = (
                    "Nao foi possivel gerar insight porque a base comparativa nao foi retornada."
                )
                presentation["recommended_next_step"] = self._default_next_step(
                    request.message,
                    response_profile=response_profile,
                    has_comparison=False,
                )
                presentation["presentation_trace"] = {
                    "source": "fallback_without_dax",
                    "matched_measure": measure_name,
                    "period_detected": presentation["period_label"],
                }
                presentation["reasoning_summary"] = [
                    "A pergunta exige valor analítico.",
                    "A execução atual retornou apenas metadados/listagem.",
                    "Sem DAX executado não há número confiável para exibir.",
                ]
                return message, presentation
            return None, None

        return self._format_dax_results(request, dax_results, power_bi_data, response_profile=response_profile)

    def _format_dax_results(
        self,
        request: UserRequest,
        dax_results: Any,
        power_bi_data: dict[str, Any],
        response_profile: str,
    ) -> tuple[str | None, dict[str, Any] | None]:
        date_filter = extract_date_filter_from_query(request.message)

        if not isinstance(dax_results, dict):
            return None, None

        value = dax_results.get("value") or dax_results.get("result")
        if value is None:
            rows = dax_results.get("rows", [])
            if rows and isinstance(rows, list) and isinstance(rows[0], dict):
                value = self._extract_first_row_value(rows[0])

        if value is None:
            return None, None

        measure_name = self._clean_text(str(dax_results.get("measure_name") or "")).strip() or "Medida"
        period_label = self._period_label_from_filter(date_filter)
        formatted_value = self._format_numeric_value(value, measure_name=measure_name)

        header = f"{measure_name}: {formatted_value}"
        if period_label:
            header = f"{measure_name} em {period_label}: {formatted_value}"

        lines = [header]
        comparison_details = self._comparison_details(dax_results, value)
        if comparison_details:
            if comparison_details["comparison_text"]:
                lines.append(comparison_details["comparison_text"])
            if comparison_details["variation_text"]:
                lines.append(comparison_details["variation_text"])

        intent_type = self._infer_intent_type(request.message, has_comparison=bool(comparison_details))
        presentation = self._base_presentation(
            intent_type=intent_type,
            response_profile=response_profile,
            measure_name=measure_name,
            period_label=period_label,
            report_context=self._report_context(power_bi_data),
        )
        presentation["primary_value"] = formatted_value
        if comparison_details:
            presentation["comparison_value"] = comparison_details["comparison_value"]
            presentation["comparison_metric_name"] = comparison_details.get("comparison_metric_name")
            presentation["delta_value"] = comparison_details["delta_value"]
            presentation["delta_percent"] = comparison_details["delta_percent"]
            presentation["comparison_basis"] = comparison_details.get("comparison_basis") or "explicit_meta"
        insight_summary = self._build_insight_summary(
            measure_name=measure_name,
            primary_value=formatted_value,
            comparison_details=comparison_details,
            response_profile=response_profile,
        )
        presentation["insight_summary"] = insight_summary
        presentation["recommended_next_step"] = self._default_next_step(
            request.message,
            response_profile=response_profile,
            has_comparison=bool(comparison_details),
        )
        presentation["presentation_trace"] = {
            "source": "dax_query_results",
            "measure_name": measure_name,
            "period_detected": period_label,
            "raw_value": value,
            "formatted_value": formatted_value,
            "has_comparison": bool(comparison_details),
            "comparison_details": comparison_details,
        }
        lines.append(insight_summary)
        presentation["reasoning_summary"] = self._build_reasoning_summary(
            measure_name=measure_name,
            period_label=period_label,
            comparison_details=comparison_details,
            value=value,
            formatted_value=formatted_value,
        )
        lines.append(f"Próximo passo: {presentation['recommended_next_step']}")
        return "\n".join(lines), presentation

    def _comparison_details(self, dax_results: dict[str, Any], primary_value: Any) -> dict[str, Any] | None:
        rows = dax_results.get("rows")
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            return None

        row = rows[0]
        baseline = self._first_present_value(
            row,
            keys=("ComparisonValue", "[ComparisonValue]", "ValorComparacao", "PreviousValue", "MetaValue"),
        )
        if baseline is None:
            return None

        primary_num = self._parse_number_like(self._clean_text(str(primary_value)))
        baseline_num = self._parse_number_like(self._clean_text(str(baseline)))
        if primary_num is None or baseline_num is None:
            return {
                "comparison_text": f"Comparação: {self._clean_text(str(baseline))}",
                "variation_text": None,
                "comparison_metric_name": self._first_present_value(
                    row,
                    keys=("ComparisonMetricName", "[ComparisonMetricName]"),
                ),
                "comparison_basis": self._first_present_value(
                    row,
                    keys=("ComparisonBasis", "[ComparisonBasis]"),
                ),
                "comparison_value": self._clean_text(str(baseline)),
                "delta_value": None,
                "delta_percent": None,
            }

        delta = primary_num - baseline_num
        delta_percent = (delta / baseline_num * 100.0) if baseline_num != 0 else None
        comparison_value = self._format_numeric_value(baseline)
        delta_value_text = self._format_numeric_value(delta)
        delta_percent_text = (
            f"{self._format_pt_br_number(delta_percent, decimals=2)}%"
            if delta_percent is not None
            else None
        )
        sign = "+" if delta > 0 else ""
        variation_text = f"Variacao: {sign}{delta_value_text}"
        if delta_percent_text:
            variation_text += f" ({sign}{delta_percent_text})"
        return {
            "comparison_text": f"Comparação: {comparison_value}",
            "variation_text": variation_text,
            "comparison_metric_name": self._first_present_value(
                row,
                keys=("ComparisonMetricName", "[ComparisonMetricName]"),
            ),
            "comparison_basis": self._first_present_value(
                row,
                keys=("ComparisonBasis", "[ComparisonBasis]"),
            ),
            "comparison_value": comparison_value,
            "delta_value": f"{sign}{delta_value_text}",
            "delta_percent": f"{sign}{delta_percent_text}" if delta_percent_text else None,
        }

    def _extract_first_row_value(self, row: Any) -> Any:
        if not isinstance(row, dict):
            return None
        preferred_keys = ("value", "Value", "Valor", "MetricValue", "[MetricValue]")
        for key in preferred_keys:
            if key in row and row.get(key) not in (None, ""):
                return row.get(key)
        for _, row_value in row.items():
            if row_value not in (None, ""):
                return row_value
        return None

    def _format_numeric_value(self, value: Any, *, measure_name: str | None = None) -> str:
        if isinstance(value, (int, float)):
            numeric_value = float(value)
            if self._looks_like_percent_measure(measure_name) and abs(numeric_value) <= 1:
                return f"{self._format_pt_br_number(numeric_value * 100.0, decimals=2)}%"
            if isinstance(value, float) and not value.is_integer():
                return self._format_pt_br_number(value, decimals=2)
            return self._format_pt_br_number(float(value), decimals=0)

        text = self._clean_text(str(value)).strip()
        if not text:
            return text
        parsed = self._parse_number_like(text)
        if parsed is None:
            return text
        if self._looks_like_percent_measure(measure_name) and abs(parsed) <= 1:
            return f"{self._format_pt_br_number(parsed * 100.0, decimals=2)}%"
        decimals = 0 if parsed.is_integer() else 2
        return self._format_pt_br_number(parsed, decimals=decimals)

    def _looks_like_percent_measure(self, measure_name: str | None) -> bool:
        if not measure_name:
            return False
        normalized = self._clean_text(measure_name).lower()
        return "%" in normalized or "percentual" in normalized or "percent" in normalized

    def _parse_number_like(self, text: str) -> float | None:
        candidate = text.replace(" ", "")
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

    def _ranking_query_message(self, power_bi_data: dict[str, Any]) -> str | None:
        ranking = power_bi_data.get("ranking_analysis")
        if not isinstance(ranking, dict):
            return None
        entity_name = ranking.get("entity_name")
        entity_type = ranking.get("entity_type")
        measure_name = ranking.get("measure_name")
        entity_value = ranking.get("entity_value")
        entity_rank = ranking.get("entity_rank")
        top_entity_name = ranking.get("top_entity_name")
        top_entity_value = ranking.get("top_entity_value")
        is_top_entity = ranking.get("is_top_entity")
        if not entity_name or not entity_type or not measure_name:
            return None

        if is_top_entity is True:
            lines = [
                f"{entity_name} e o {entity_type} com maior {measure_name}.",
                f"Valor: {entity_value}.",
            ]
        else:
            lines = [
                f"{entity_name} nao e o {entity_type} com maior {measure_name}.",
                f"{top_entity_name} lidera com {top_entity_value}.",
            ]
            if entity_rank:
                lines.append(f"{entity_name} esta na posicao {entity_rank} com {entity_value}.")
        return "\n".join(lines)

    def _ranking_presentation(self, request: UserRequest, power_bi_data: dict[str, Any]) -> dict[str, Any]:
        ranking = power_bi_data.get("ranking_analysis")
        measure_name = None
        primary_value = None
        comparison_value = None
        delta_value = None
        if isinstance(ranking, dict):
            measure_name = ranking.get("measure_name")
            primary_value = ranking.get("entity_value")
            comparison_value = ranking.get("top_entity_value")
            rank = ranking.get("entity_rank")
            if rank is not None:
                delta_value = f"Posicao: {rank}"
        presentation = self._base_presentation(
            intent_type="ranking",
            response_profile=self._response_profile(request),
            measure_name=measure_name,
            period_label=self._period_label_from_request(request.message),
            report_context=self._report_context(power_bi_data),
        )
        presentation["primary_value"] = str(primary_value) if primary_value is not None else None
        presentation["comparison_value"] = str(comparison_value) if comparison_value is not None else None
        presentation["delta_value"] = delta_value
        presentation["insight_summary"] = (
            "A entidade consultada nao lidera o ranking." if comparison_value else "Ranking retornado."
        )
        presentation["recommended_next_step"] = "Avaliar os 3 primeiros colocados e comparar conversao por periodo."
        return presentation

    def _power_bi_message(
        self,
        request: UserRequest,
        orchestration: NormalizedResponse,
        response_profile: str,
    ) -> tuple[str | None, dict[str, Any] | None]:
        power_bi_data = None
        if isinstance(orchestration.structured_data, dict):
            power_bi_data = orchestration.structured_data.get("power_bi")
        if not isinstance(power_bi_data, dict):
            return None, None

        connection = power_bi_data.get("connection")
        if not isinstance(connection, dict):
            return None, None

        tables = power_bi_data.get("tables")
        measures = power_bi_data.get("measures")
        matching_measures = power_bi_data.get("matching_measures")
        measure_definitions = power_bi_data.get("measure_definitions")
        columns = power_bi_data.get("columns")

        lines: list[str] = []
        intent_type = "insight"
        if isinstance(tables, list):
            table_names = [
                str(table.get("name"))
                for table in tables
                if isinstance(table, dict) and table.get("name")
            ]
            table_names = [name for name in table_names if self._is_business_table_name(name)]
            if table_names:
                lines.append(
                    f"Modelo conectado com {len(table_names)} tabelas. "
                    f"Principais: {', '.join(table_names[:6])}."
                )

        column_lines = self._format_columns(columns)
        if column_lines:
            lines.extend(column_lines)

        definition_lines = self._format_measure_definitions(measure_definitions)
        if definition_lines:
            lines.extend(definition_lines)
            intent_type = "definicao"
        elif isinstance(matching_measures, list) and matching_measures:
            label = self._measure_label(request.message)
            names = self._names(matching_measures)
            lines.append(f"{label} ({len(names)}): {self._limited_join(names, limit=15)}.")
            lines.append("Posso refinar por tema: meta, vgv, proposta ou conversao.")
            intent_type = "lista"
        elif isinstance(measures, list):
            names = self._names(measures)
            if self._asks_for_measure_names(request.message) and names:
                lines.append(f"Medidas encontradas ({len(names)}): {self._limited_join(names, limit=15)}.")
                lines.append("Se quiser, te mostro só as de Meta, VGV ou Propostas.")
                intent_type = "lista"
            else:
                lines.append(
                    f"Consegui acessar o modelo e identificar {len(measures)} medidas. "
                    "Me diga qual KPI voce quer analisar e eu trago comparacao e insight."
                )
                intent_type = "insight"
        if not lines and self._is_status_question(request.message):
            presentation = self._base_presentation(
                intent_type="status",
                response_profile=response_profile,
                measure_name=None,
                period_label=None,
                report_context=self._report_context(power_bi_data),
            )
            return "Conexão Power BI ativa.", presentation
        if not lines:
            message = "Não encontrei dados analíticos suficientes para gerar insight nesta consulta."
            presentation = self._base_presentation(
                intent_type="insight",
                response_profile=response_profile,
                measure_name=None,
                period_label=None,
                report_context=self._report_context(power_bi_data),
            )
            return message, presentation
        presentation = self._base_presentation(
            intent_type=intent_type,
            response_profile=response_profile,
            measure_name=None,
            period_label=self._period_label_from_request(request.message),
            report_context=self._report_context(power_bi_data),
        )
        presentation["insight_summary"] = (
            "Resposta resumida para manter o chat limpo; detalhes tecnicos ficam no painel lateral."
        )
        return "\n".join(lines), presentation

    def _report_context(self, power_bi_data: dict[str, Any]) -> dict[str, Any] | None:
        connection = power_bi_data.get("connection")
        if not isinstance(connection, dict):
            return None
        return {
            "title": connection.get("parentWindowTitle"),
            "process": connection.get("parentProcessName"),
            "port": connection.get("port"),
        }

    def _base_presentation(
        self,
        *,
        intent_type: str,
        response_profile: str,
        measure_name: str | None,
        period_label: str | None,
        report_context: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "intent_type": intent_type,
            "response_profile": response_profile,
            "primary_metric_name": self._clean_text(measure_name or "") or None,
            "primary_value": None,
            "comparison_value": None,
            "comparison_metric_name": None,
            "delta_value": None,
            "delta_percent": None,
            "comparison_basis": None,
            "period_label": period_label,
            "insight_summary": None,
            "recommended_next_step": None,
            "report_context": report_context,
            "presentation_trace": None,
            "reasoning_summary": None,
            "ui_hints": {"show_reasoning": True},
        }

    def _period_label_from_filter(self, date_filter: Any) -> str | None:
        if not isinstance(date_filter, dict):
            return None
        parts: list[str] = []
        month = date_filter.get("month")
        if month:
            months = [
                "janeiro",
                "fevereiro",
                "marco",
                "abril",
                "maio",
                "junho",
                "julho",
                "agosto",
                "setembro",
                "outubro",
                "novembro",
                "dezembro",
            ]
            month_idx = int(month) - 1
            if 0 <= month_idx < len(months):
                parts.append(months[month_idx])
        if date_filter.get("year"):
            parts.append(f"de {date_filter['year']}")
        return " ".join(parts) if parts else None

    def _period_label_from_request(self, message: str) -> str | None:
        return self._period_label_from_filter(extract_date_filter_from_query(message))

    def _infer_intent_type(self, message: str, *, has_comparison: bool) -> str:
        normalized = self._clean_text(message).lower()
        if "ranking" in normalized or "top" in normalized:
            return "ranking"
        if has_comparison or any(token in normalized for token in {"compar", "versus", " vs "}):
            return "comparacao"
        if any(token in normalized for token in {"variacao", "delta"}):
            return "variacao"
        return "valor"

    def _first_present_value(self, row: dict[str, Any], *, keys: tuple[str, ...]) -> Any:
        for key in keys:
            if key in row and row.get(key) not in (None, ""):
                return row[key]
        return None

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
                    f"Colunas da tabela {table_name} ({len(names)}): {self._limited_join(names, limit=40)}."
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

    def _asks_for_measure_value(self, message: str) -> bool:
        normalized = self._clean_text(message).lower()
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
            }
        )
        mentions_measure = any(
            token in normalized for token in {"medida", "measure", "meta", "vgv", "propostas"}
        )
        return asks_value and mentions_measure

    def _asks_for_analytical_value(self, message: str) -> bool:
        normalized = self._clean_text(message).lower()
        if self._asks_for_measure_value(message):
            return True
        return any(
            token in normalized
            for token in {"compar", " vs ", "versus", "meta", "atingimento", "variacao", "diferen"}
        ) and any(token in normalized for token in {"vgv", "meta", "medida", "measure", "proposta"})

    def _is_analytical_query(self, message: str) -> bool:
        normalized = self._clean_text(message).lower()
        if any(
            token in normalized
            for token in {
                "o que e",
                "o que é",
                "oque e",
                "oque é",
                "significa",
                "conceito",
                "onde aplico",
                "como aplicar",
                "para que serve",
                "pra que serve",
            }
        ):
            return False
        if self._asks_for_analytical_value(message):
            return True
        return any(
            token in normalized
            for token in {"kpi", "insight", "compar", "variacao", "meta", "resultado", "total"}
        )

    def _context_key(self, request: UserRequest) -> str:
        domain = self._clean_text(str(request.domain_hint or "power_bi")).lower()
        profile = self._response_profile(request)
        return f"{domain}:{profile}"

    def _update_analysis_context(self, request: UserRequest, presentation: dict[str, Any]) -> None:
        metric = presentation.get("primary_metric_name")
        if not metric:
            return
        key = self._context_key(request)
        self._analysis_context_by_key[key] = {
            "last_metric_name": metric,
            "last_comparison_metric_name": presentation.get("comparison_metric_name"),
            "last_period_label": presentation.get("period_label"),
        }

    def _measure_label(self, message: str) -> str:
        normalized = message.lower()
        if "falam" in normalized or "sobre" in normalized:
            return "Medidas relacionadas"
        return "Medidas encontradas"

    def _response_profile(self, request: UserRequest) -> str:
        profile = request.metadata.get("response_profile") if isinstance(request.metadata, dict) else None
        normalized = self._clean_text(str(profile or "")).strip().lower()
        return "creator" if normalized == "creator" else "business"

    def _build_insight_summary(
        self,
        *,
        measure_name: str,
        primary_value: str,
        comparison_details: dict[str, Any] | None,
        response_profile: str,
    ) -> str:
        if comparison_details and comparison_details.get("delta_value"):
            delta = comparison_details.get("delta_value")
            direction = "acima" if str(delta).startswith("+") else "abaixo"
            if response_profile == "creator":
                return (
                    f"Insight: {measure_name} está {direction} da base comparativa ({delta}); "
                    "vale validar composição por segmento e período."
                )
            return f"Insight: {measure_name} está {direction} da base de comparação."
        if response_profile == "creator":
            return (
                f"Insight: {measure_name} retornou {primary_value}; sem base comparativa explícita, "
                "a leitura de tendência ainda está inconclusiva."
            )
        return f"Insight: {measure_name} retornou {primary_value}; faltou base comparativa para tendência."

    def _build_reasoning_summary(
        self,
        *,
        measure_name: str,
        period_label: str | None,
        comparison_details: dict[str, Any] | None,
        value: Any,
        formatted_value: str,
    ) -> list[str]:
        steps = [
            f"Consultei a medida '{measure_name}' no resultado executado.",
            f"Valor bruto retornado: {self._clean_text(str(value))}.",
            f"Valor exibido em PT-BR: {formatted_value}.",
        ]
        if period_label:
            steps.insert(1, f"Período identificado: {period_label}.")
        if comparison_details and comparison_details.get("comparison_value"):
            steps.append(f"Base comparativa usada: {comparison_details['comparison_value']}.")
        else:
            steps.append("Não houve base comparativa confiável nesta execução.")
        return steps[:4]

    def _default_next_step(self, message: str, *, response_profile: str, has_comparison: bool) -> str:
        period = self._period_label_from_request(message) or "o periodo anterior"
        if has_comparison:
            return (
                "Quebre o resultado por unidade/segmento para identificar os maiores vetores de impacto."
                if response_profile == "business"
                else "Executar corte por dimensão-chave (unidade, canal, produto) e medir contribuição percentual."
            )
        return (
            f"Compare com {period} e com a meta correspondente para concluir tendência."
            if response_profile == "business"
            else f"Rodar a mesma medida para {period} e meta da família para derivar delta absoluto e percentual."
        )

    def _is_status_question(self, message: str) -> bool:
        normalized = self._clean_text(message).lower()
        return any(token in normalized for token in {"conexao", "conexao", "instancia", "relatorio aberto", "status"})

    def _clean_text(self, value: str) -> str:
        if any(marker in value for marker in ("Ãƒ", "Ã‚", "ï¿½")):
            try:
                return value.encode("latin1").decode("utf-8")
            except UnicodeError:
                return value
        return value

    def _is_business_table_name(self, name: str) -> bool:
        normalized = self._clean_text(name).strip().lower()
        if normalized.startswith("localdatatable_"):
            return False
        if normalized.startswith("datetabletemplate_"):
            return False
        return True
