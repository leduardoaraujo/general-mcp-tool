"""
MCP Resources - Schema

Exposição do schema do banco de dados através de resources MCP.
"""

import json
import logging

from mcp.server.fastmcp import FastMCP

from app.services.discovery import discovery_service

logger = logging.getLogger(__name__)


def format_schema_overview(db_map) -> str:
    """Formata um resumo do schema para exibição."""
    lines = [
        f"# Schema Overview: {db_map.database_alias}",
        "",
    ]

    for schema_name, schema in sorted(db_map.schemas.items()):
        lines.append(f"## Schema: {schema_name}")
        if schema.comment:
            lines.append(f"*{schema.comment}*")
        lines.append("")

        for table_name, table in sorted(schema.tables.items()):
            row_info = f" (~{table.row_estimate:,} rows)" if table.row_estimate else ""
            lines.append(f"- **{table_name}** ({table.size}){row_info}")
            if table.comment:
                lines.append(f"  - {table.comment}")

        lines.append("")

    return "\n".join(lines)


def get_detailed_table_info(db_map, schema: str, table: str) -> str:
    """Obtém informações detalhadas de uma tabela."""
    table_info = db_map.get_table(schema, table)
    if not table_info:
        return f"Tabela {schema}.{table} não encontrada."

    lines = [
        f"# Tabela: {schema}.{table}",
        "",
    ]

    if table_info.comment:
        lines.append(f"**Descrição:** {table_info.comment}")
        lines.append("")

    lines.append(f"**Tamanho:** {table_info.size}")
    if table_info.row_estimate:
        lines.append(f"**Estimativa de linhas:** {table_info.row_estimate:,}")
    lines.append("")

    # Colunas
    lines.append("## Colunas")
    lines.append("")
    lines.append("| Coluna | Tipo | Nullable | Default | PK | Descrição |")
    lines.append("|--------|------|----------|---------|----|-------------|")

    for col_name, col in sorted(table_info.columns.items()):
        pk = "✓" if col.is_primary_key else ""
        nullable = "✓" if col.is_nullable else ""
        default = col.default_value or ""
        desc = col.comment or ""
        lines.append(
            f"| {col_name} | {col.data_type} | {nullable} | {default} | {pk} | {desc} |"
        )

    lines.append("")

    # Foreign Keys
    if table_info.foreign_keys:
        lines.append("## Chaves Estrangeiras")
        lines.append("")
        for fk in table_info.foreign_keys:
            lines.append(
                f"- `{fk['column']}` → "
                f"`{fk['ref_schema']}.{fk['ref_table']}.{fk['ref_column']}`"
            )
        lines.append("")

    # Índices
    if table_info.indexes:
        lines.append("## Índices")
        lines.append("")
        for idx in table_info.indexes:
            lines.append(f"- **{idx['name']}**: `{idx['definition']}`")
        lines.append("")

    return "\n".join(lines)


def register_schema_resources(mcp: FastMCP) -> None:
    """Registra resources relacionados ao schema."""

    @mcp.resource("resource://schema/overview")
    async def get_schema_overview() -> str:
        """
        Retorna visão geral do schema de todos os bancos.
        """
        all_maps = discovery_service.get_all_maps()

        if not all_maps:
            return """
# Schema Overview

O schema ainda não foi descoberto. Aguarde a inicialização do servidor
ou consulte as tabelas disponíveis usando pg_list_tables.
"""

        sections = []
        for alias, db_map in sorted(all_maps.items()):
            sections.append(format_schema_overview(db_map))
            sections.append("---")

        return "\n".join(sections)

    @mcp.resource("resource://schema/{database}/{schema}/{table}")
    async def get_table_details(database: str, schema: str, table: str) -> str:
        """
        Retorna detalhes de uma tabela específica.

        Args:
            database: Alias do banco
            schema: Nome do schema
            table: Nome da tabela
        """
        db_map = discovery_service.get_map(database)

        if not db_map:
            return f"Banco '{database}' não encontrado ou ainda não descoberto."

        return get_detailed_table_info(db_map, schema, table)

    @mcp.resource("resource://schema/json")
    async def get_schema_json() -> str:
        """
        Retorna o schema completo em formato JSON.
        Útil para processamento programático.
        """
        all_maps = discovery_service.get_all_maps()

        if not all_maps:
            return json.dumps({"error": "Schema not yet discovered"}, indent=2)

        data = {
            alias: db_map.to_dict()
            for alias, db_map in sorted(all_maps.items())
        }

        return json.dumps(data, indent=2, ensure_ascii=False)
