"""
Semantic Tools

Ferramentas de alto nível orientadas a intenção para análise de dados.
Estas ferramentas orquestram múltiplas operações para fornecer
uma experiência semântica ao usuário.
"""

import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult
from pydantic import BaseModel, ConfigDict, Field

from app.services.discovery import discovery_service
from app.services.rag import rag_service
from app.services.semantic_mapper import SemanticMatch, semantic_mapper
from core.connection import apply_readonly_session_guards, get_pool, resolve_database_alias
from core.errors import MCPToolError, sanitize_error
from core.formatters import format_as_markdown_table, records_to_dict
from core.query_validation import normalize_readonly_query
from core.tool_results import (
    ToolErrorPayload,
    error_result,
    success_result,
)

logger = logging.getLogger(__name__)


class DiscoverDatabaseContextInput(BaseModel):
    """Input para descoberta de contexto."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: str = Field(
        ...,
        description="Pergunta ou contexto sobre o que quer descobrir",
        min_length=1,
    )
    database: Optional[str] = Field(
        default=None,
        description="Alias do banco (usa o padrão se omitido)",
    )


class FindRelevantTablesInput(BaseModel):
    """Input para encontrar tabelas relevantes."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: str = Field(
        ...,
        description="Pergunta para identificar tabelas relevantes",
        min_length=1,
    )
    database: Optional[str] = Field(
        default=None,
        description="Alias do banco (usa o padrão se omitido)",
    )


class GenerateSafeSqlInput(BaseModel):
    """Input para geração de SQL segura."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: str = Field(
        ...,
        description="Pergunta em linguagem natural para gerar SQL",
        min_length=1,
    )
    database: Optional[str] = Field(
        default=None,
        description="Alias do banco (usa o padrão se omitido)",
    )
    context_tables: Optional[list[str]] = Field(
        default=None,
        description="Tabelas sugeridas para usar no contexto",
    )


class RunGuidedQueryInput(BaseModel):
    """Input para execução de query guiada."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    question: str = Field(
        ...,
        description="Pergunta em linguagem natural",
        min_length=1,
    )
    database: Optional[str] = Field(
        default=None,
        description="Alias do banco (usa o padrão se omitido)",
    )
    auto_execute: bool = Field(
        default=False,
        description="Se True, executa a query automaticamente. Se False, retorna SQL para aprovação.",
    )
    limit: int = Field(
        default=100,
        description="Limite de linhas",
        ge=1,
        le=5000,
    )


def _format_discover_result(
    question: str,
    database: str,
    matches: list[SemanticMatch],
    rag_results: list[dict],
) -> str:
    """Formata resultado da descoberta."""
    lines = [
        f"## Análise da Pergunta: \"{question}\"",
        "",
        f"**Banco:** `{database}`",
        "",
    ]

    if matches:
        lines.append("### Tabelas Relevantes Encontradas")
        lines.append("")
        lines.append("| Tabela | Schema | Confiança | Motivo |")
        lines.append("|--------|--------|-----------|--------|")

        seen = set()
        for m in matches[:10]:
            key = (m.schema, m.matched_table)
            if key not in seen:
                seen.add(key)
                lines.append(
                    f"| {m.matched_table} | {m.schema} | {m.confidence:.0%} | {m.reason} |"
                )
        lines.append("")
    else:
        lines.append("*Nenhuma tabela diretamente identificada para esta pergunta.*")
        lines.append("")

    if rag_results:
        lines.append("### Contexto Adicional (RAG)")
        lines.append("")
        for r in rag_results[:5]:
            lines.append(f"- **{r['type']}** (score: {r['score']}): {r['content'][:100]}...")
        lines.append("")

    lines.append("### Sugestões")
    lines.append("")
    if matches:
        top_table = matches[0]
        lines.append(f"- Use `pg_describe_table` para explorar `{top_table.schema}.{top_table.matched_table}`")
    lines.append("- Refine sua pergunta com termos mais específicos")
    lines.append("- Consulte `resource://schema/overview` para ver todas as tabelas")

    return "\n".join(lines)


def _format_sql_generation_result(
    question: str,
    sql: str,
    assumptions: list[str],
    warnings: list[str],
) -> str:
    """Formata resultado da geração de SQL."""
    lines = [
        f"## SQL Gerada para: \"{question}\"",
        "",
        "```sql",
        sql,
        "```",
        "",
    ]

    if assumptions:
        lines.append("### Premissas")
        lines.append("")
        for a in assumptions:
            lines.append(f"- {a}")
        lines.append("")

    if warnings:
        lines.append("### Avisos")
        lines.append("")
        for w in warnings:
            lines.append(f"- ⚠️ {w}")
        lines.append("")

    return "\n".join(lines)


def _format_guided_query_result(
    question: str,
    sql: str,
    result_preview: list[dict],
    row_count: int,
    next_steps: list[str],
) -> str:
    """Formata resultado da query guiada."""
    lines = [
        f"## Resultado: \"{question}\"",
        "",
        f"**SQL Executada:**",
        "```sql",
        sql,
        "```",
        "",
        f"**Linhas retornadas:** {row_count}",
        "",
    ]

    if result_preview:
        lines.append("### Preview dos Dados")
        lines.append("")
        lines.append(format_as_markdown_table(result_preview))
        lines.append("")

    if next_steps:
        lines.append("### Próximos Passos Sugeridos")
        lines.append("")
        for step in next_steps:
            lines.append(f"- {step}")

    return "\n".join(lines)


def register_semantic_tools(mcp: FastMCP) -> None:
    """Registra ferramentas semânticas de alto nível."""

    @mcp.tool(
        name="discover_database_context",
        annotations={"title": "Discover Database Context", "readOnlyHint": True},
    )
    async def discover_database_context(params: DiscoverDatabaseContextInput) -> CallToolResult:
        """
        Descobre quais partes do banco podem responder a uma pergunta.

        Analisa a pergunta do usuário e identifica:
        - Schemas relevantes
        - Tabelas candidatas
        - Contexto adicional via RAG (se disponível)
        """
        database = None
        try:
            database = resolve_database_alias(params.database)
            db_map = discovery_service.get_map(database)

            if not db_map:
                return error_result(
                    f"Banco '{database}' ainda não foi descoberto. Aguarde a inicialização.",
                    ToolErrorPayload(
                        code="schema_not_ready",
                        message="Database schema not yet discovered",
                        database=database,
                        retryable=True,
                    ),
                )

            # Busca por mapeamento semântico
            semantic_matches = semantic_mapper.find_tables(params.question)

            # Busca por RAG se disponível
            rag_results = []
            if rag_service.is_available():
                rag_results = rag_service.find_relevant_tables(params.question)

            text = _format_discover_result(
                params.question,
                database,
                semantic_matches,
                rag_results,
            )

            payload = {
                "database": database,
                "question": params.question,
                "candidate_tables": [m.to_dict() for m in semantic_matches[:10]],
                "rag_context": rag_results[:5],
            }

            return success_result(text, payload)

        except Exception as exc:
            tool_error = sanitize_error(exc, database=database)
            logger.warning(f"discover_database_context failed: {tool_error.code}")
            return error_result(
                tool_error.message,
                ToolErrorPayload(
                    code=tool_error.code,
                    message=tool_error.message,
                    database=tool_error.database or database,
                    retryable=tool_error.retryable,
                ),
            )

    @mcp.tool(
        name="find_relevant_tables",
        annotations={"title": "Find Relevant Tables", "readOnlyHint": True},
    )
    async def find_relevant_tables(params: FindRelevantTablesInput) -> CallToolResult:
        """
        Encontra tabelas e colunas relevantes para uma pergunta.

        Usa mapeamento semântico para traduzir termos humanos
        em referências a tabelas e colunas reais.
        """
        database = None
        try:
            database = resolve_database_alias(params.database)
            db_map = discovery_service.get_map(database)

            if not db_map:
                return error_result(
                    f"Banco '{database}' ainda não foi descoberto.",
                    ToolErrorPayload(
                        code="schema_not_ready",
                        message="Database schema not yet discovered",
                        database=database,
                        retryable=True,
                    ),
                )

            # Resolve o conceito usando o mapper semântico
            resolution = semantic_mapper.resolve_concept(params.question)

            # Formata resultado
            lines = [
                f"## Tabelas Relevantes para: \"{params.question}\"",
                "",
            ]

            if resolution["tables"]:
                lines.append("### Tabelas Sugeridas")
                lines.append("")
                for t in resolution["tables"]:
                    lines.append(f"- `{t['schema']}.{t['matched_table']}` ({t['confidence']:.0%})")
                lines.append("")

            if resolution["columns"]:
                lines.append("### Colunas Relevantes")
                lines.append("")
                lines.append("| Coluna | Tabela | Schema | Confiança |")
                lines.append("|--------|--------|--------|-----------|")
                for c in resolution["columns"][:10]:
                    lines.append(
                        f"| {c['matched_column']} | {c['matched_table']} | {c['schema']} | {c['confidence']:.0%} |"
                    )
                lines.append("")

            return success_result(
                "\n".join(lines),
                {
                    "database": database,
                    "concept": params.question,
                    "tables": resolution["tables"],
                    "columns": resolution["columns"],
                    "suggested_tables": resolution["suggested_tables"],
                },
            )

        except Exception as exc:
            tool_error = sanitize_error(exc, database=database)
            logger.warning(f"find_relevant_tables failed: {tool_error.code}")
            return error_result(
                tool_error.message,
                ToolErrorPayload(
                    code=tool_error.code,
                    message=tool_error.message,
                    database=tool_error.database or database,
                    retryable=tool_error.retryable,
                ),
            )

    @mcp.tool(
        name="generate_safe_sql",
        annotations={"title": "Generate Safe SQL", "readOnlyHint": True},
    )
    async def generate_safe_sql(params: GenerateSafeSqlInput) -> CallToolResult:
        """
        Gera SQL segura para responder uma pergunta.

        IMPORTANTE: Esta ferramenta apenas GERA a SQL, não a executa.
        Use pg_execute_query ou run_guided_query para executar.

        A SQL gerada segue todas as diretrizes de segurança:
        - Sem SELECT *
        - Com LIMIT aplicado
        - Apenas leitura
        """
        database = None
        try:
            database = resolve_database_alias(params.database)
            db_map = discovery_service.get_map(database)

            if not db_map:
                return error_result(
                    f"Banco '{database}' ainda não foi descoberto.",
                    ToolErrorPayload(
                        code="schema_not_ready",
                        message="Database schema not yet discovered",
                        database=database,
                        retryable=True,
                    ),
                )

            # Encontra tabelas relevantes
            resolution = semantic_mapper.resolve_concept(params.question)

            # Monta SQL básica com base nas tabelas sugeridas
            suggested_tables = params.context_tables or resolution["suggested_tables"][:1]

            if not suggested_tables:
                return error_result(
                    "Não foi possível identificar tabelas relevantes para esta pergunta.",
                    ToolErrorPayload(
                        code="no_relevant_tables",
                        message="No relevant tables found for the question",
                        database=database,
                        retryable=False,
                    ),
                )

            # Extrai schema e tabela
            parts = suggested_tables[0].split(".", 1)
            schema = parts[0] if len(parts) > 1 else "public"
            table = parts[1] if len(parts) > 1 else parts[0]

            table_info = db_map.get_table(schema, table)
            if not table_info:
                return error_result(
                    f"Tabela {schema}.{table} não encontrada.",
                    ToolErrorPayload(
                        code="table_not_found",
                        message=f"Table {schema}.{table} not found",
                        database=database,
                        retryable=False,
                    ),
                )

            # Gera SQL básica (template)
            columns = list(table_info.columns.keys())[:5]  # Primeiras 5 colunas
            if not columns:
                columns = ["*"]

            sql = f"SELECT {', '.join(columns)}\nFROM {schema}.{table}\nLIMIT 100"

            assumptions = [
                f"Usando tabela principal: {schema}.{table}",
                f"Selecionadas colunas: {', '.join(columns)}",
                "LIMIT 100 aplicado por segurança",
            ]

            warnings = []
            if len(suggested_tables) > 1:
                warnings.append(
                    f"Mais de uma tabela identificada: {', '.join(suggested_tables)}"
                )

            text = _format_sql_generation_result(
                params.question,
                sql,
                assumptions,
                warnings,
            )

            return success_result(
                text,
                {
                    "database": database,
                    "question": params.question,
                    "sql": sql,
                    "suggested_tables": suggested_tables,
                    "relevant_columns": [c["matched_column"] for c in resolution["columns"][:5]],
                    "assumptions": assumptions,
                    "warnings": warnings,
                },
            )

        except Exception as exc:
            tool_error = sanitize_error(exc, database=database)
            logger.warning(f"generate_safe_sql failed: {tool_error.code}")
            return error_result(
                tool_error.message,
                ToolErrorPayload(
                    code=tool_error.code,
                    message=tool_error.message,
                    database=tool_error.database or database,
                    retryable=tool_error.retryable,
                ),
            )

    @mcp.tool(
        name="run_guided_query",
        annotations={"title": "Run Guided Query", "readOnlyHint": True},
    )
    async def run_guided_query(params: RunGuidedQueryInput) -> CallToolResult:
        """
        Executa um fluxo completo de consulta guiada.

        Fluxo: pergunta → encontra tabelas → gera SQL → valida → executa → resume

        Se auto_execute=False, retorna a SQL gerada para aprovação.
        Se auto_execute=True, executa e retorna os resultados.
        """
        database = None
        try:
            database = resolve_database_alias(params.database)

            if not params.auto_execute:
                # Modo preview - apenas gera SQL
                sql_result = await generate_safe_sql(
                    GenerateSafeSqlInput(
                        question=params.question,
                        database=params.database,
                    )
                )

                # Extrai a SQL do resultado
                payload = sql_result.structuredContent
                if isinstance(payload, dict):
                    sql = payload.get("sql", "")
                    assumptions = payload.get("assumptions", [])
                else:
                    sql = "-- SQL não disponível"
                    assumptions = []

                text = f"""
## Preview da Query

**Pergunta:** {params.question}

**SQL que será executada:**
```sql
{sql}
```

### Para executar esta query, use:
```
run_guided_query com auto_execute=true
```

Ou execute manualmente via `pg_execute_query`.
"""
                return success_result(
                    text,
                    {
                        "database": database,
                        "question": params.question,
                        "sql": sql,
                        "assumptions": assumptions,
                        "preview_only": True,
                    },
                )

            # Modo execução - gera e executa
            sql_result = await generate_safe_sql(
                GenerateSafeSqlInput(
                    question=params.question,
                    database=params.database,
                )
            )

            payload = sql_result.structuredContent
            if not isinstance(payload, dict) or not payload.get("sql"):
                return error_result(
                    "Não foi possível gerar SQL para esta pergunta.",
                    ToolErrorPayload(
                        code="sql_generation_failed",
                        message="Failed to generate SQL",
                        database=database,
                        retryable=False,
                    ),
                )

            sql = payload["sql"]

            # Valida e executa a query
            normalized = normalize_readonly_query(sql, params.limit)
            pool = await get_pool(database)

            async with pool.acquire() as conn:
                async with conn.transaction():
                    await apply_readonly_session_guards(conn)
                    records = await conn.fetch(normalized.sql)

            data = records_to_dict(records)

            # Sugere próximos passos
            next_steps = []
            if len(data) >= params.limit:
                next_steps.append(f"Aumente o limite (atual: {params.limit}) para ver mais resultados")
            if len(payload.get("suggested_tables", [])) > 1:
                next_steps.append("Explore JOINs com outras tabelas identificadas")
            next_steps.append("Use pg_describe_table para entender melhor os dados")

            text = _format_guided_query_result(
                params.question,
                normalized.sql,
                data[:10],  # Preview de 10 linhas
                len(data),
                next_steps,
            )

            return success_result(
                text,
                {
                    "database": database,
                    "question": params.question,
                    "sql_executed": normalized.sql,
                    "row_count": len(data),
                    "result_preview": data[:10],
                    "next_steps": next_steps,
                },
            )

        except Exception as exc:
            tool_error = sanitize_error(exc, database=database)
            logger.warning(f"run_guided_query failed: {tool_error.code}")
            return error_result(
                tool_error.message,
                ToolErrorPayload(
                    code=tool_error.code,
                    message=tool_error.message,
                    database=tool_error.database or database,
                    retryable=tool_error.retryable,
                ),
            )
