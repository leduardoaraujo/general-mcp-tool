"""
Database Discovery Service

Constrói e mantém um mapa semântico do banco de dados,
incluindo schemas, tabelas, colunas, tipos e comentários.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from core.connection import get_pool, get_settings

logger = logging.getLogger(__name__)


@dataclass
class ColumnInfo:
    """Informações sobre uma coluna."""

    name: str
    data_type: str
    is_nullable: bool
    default_value: Optional[str] = None
    comment: Optional[str] = None
    is_primary_key: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.data_type,
            "nullable": self.is_nullable,
            "default": self.default_value,
            "comment": self.comment,
            "is_pk": self.is_primary_key,
        }


@dataclass
class TableInfo:
    """Informações sobre uma tabela."""

    schema: str
    name: str
    columns: dict[str, ColumnInfo] = field(default_factory=dict)
    comment: Optional[str] = None
    row_estimate: Optional[int] = None
    size: Optional[str] = None
    foreign_keys: list[dict] = field(default_factory=list)
    indexes: list[dict] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.schema}.{self.name}"

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "name": self.name,
            "full_name": self.full_name,
            "comment": self.comment,
            "columns": {k: v.to_dict() for k, v in self.columns.items()},
            "row_estimate": self.row_estimate,
            "size": self.size,
        }


@dataclass
class SchemaInfo:
    """Informações sobre um schema."""

    name: str
    tables: dict[str, TableInfo] = field(default_factory=dict)
    comment: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "comment": self.comment,
            "tables": {k: v.to_dict() for k, v in self.tables.items()},
        }


@dataclass
class DatabaseMap:
    """
    Mapa completo do banco de dados.

    Estrutura:
        DatabaseMap
        ├─ schemas
        │   ├─ tables
        │   │   ├─ columns
        │   │   ├─ types
        │   │   ├─ comments
        │   │   ├─ foreign_keys
        │   │   └─ indexes
    """

    database_alias: str
    schemas: dict[str, SchemaInfo] = field(default_factory=dict)

    def get_table(self, schema: str, table: str) -> Optional[TableInfo]:
        """Obtém uma tabela pelo schema e nome."""
        schema_info = self.schemas.get(schema)
        if schema_info:
            return schema_info.tables.get(table)
        return None

    def get_column(self, schema: str, table: str, column: str) -> Optional[ColumnInfo]:
        """Obtém uma coluna específica."""
        table_info = self.get_table(schema, table)
        if table_info:
            return table_info.columns.get(column)
        return None

    def search_tables(self, pattern: str) -> list[TableInfo]:
        """Busca tabelas por padrão no nome."""
        pattern_lower = pattern.lower()
        results = []
        for schema in self.schemas.values():
            for table in schema.tables.values():
                if pattern_lower in table.name.lower():
                    results.append(table)
        return results

    def to_dict(self) -> dict:
        return {
            "database": self.database_alias,
            "schemas": {k: v.to_dict() for k, v in self.schemas.items()},
        }


class DiscoveryService:
    """
    Serviço de descoberta do banco de dados.

    Responsável por construir e atualizar o DatabaseMap
    consultando information_schema e pg_catalog.
    """

    def __init__(self):
        self._maps: dict[str, DatabaseMap] = {}

    async def discover_all(self) -> dict[str, DatabaseMap]:
        """Descobre o schema de todos os bancos configurados."""
        settings = get_settings()
        for config in settings.databases:
            if config.alias not in self._maps:
                self._maps[config.alias] = await self._discover_database(config.alias)
        return self._maps

    async def discover_database(self, alias: str) -> DatabaseMap:
        """Descobre o schema de um banco específico."""
        self._maps[alias] = await self._discover_database(alias)
        return self._maps[alias]

    async def _discover_database(self, alias: str) -> DatabaseMap:
        """Executa a descoberta do banco."""
        logger.info(f"Discovering database schema for: {alias}")
        pool = await get_pool(alias)
        db_map = DatabaseMap(database_alias=alias)

        async with pool.acquire() as conn:
            # Descobre schemas
            await self._discover_schemas(conn, db_map)

            # Descobre tabelas
            await self._discover_tables(conn, db_map)

            # Descobre colunas
            await self._discover_columns(conn, db_map)

            # Descobre comentários
            await self._discover_comments(conn, db_map)

            # Descobre chaves estrangeiras
            await self._discover_foreign_keys(conn, db_map)

            # Descobre índices
            await self._discover_indexes(conn, db_map)

        logger.info(
            f"Discovery complete for {alias}: "
            f"{len(db_map.schemas)} schemas, "
            f"{sum(len(s.tables) for s in db_map.schemas.values())} tables"
        )
        return db_map

    async def _discover_schemas(self, conn, db_map: DatabaseMap) -> None:
        """Descobre schemas do banco."""
        sql = """
            SELECT schema_name, obj_description(n.oid, 'pg_namespace') as comment
            FROM information_schema.schemata s
            LEFT JOIN pg_namespace n ON n.nspname = s.schema_name
            WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
              AND schema_name NOT LIKE 'pg_temp%'
              AND schema_name NOT LIKE 'pg_toast_temp%'
            ORDER BY schema_name
        """
        records = await conn.fetch(sql)
        for record in records:
            schema_name = record["schema_name"]
            db_map.schemas[schema_name] = SchemaInfo(
                name=schema_name,
                comment=record["comment"],
            )

    async def _discover_tables(self, conn, db_map: DatabaseMap) -> None:
        """Descobre tabelas de cada schema."""
        sql = """
            SELECT
                t.table_schema,
                t.table_name,
                pg_size_pretty(pg_total_relation_size(
                    quote_ident(t.table_schema) || '.' || quote_ident(t.table_name)
                )) AS size,
                c.reltuples::bigint AS row_estimate,
                obj_description(c.oid, 'pg_class') AS comment
            FROM information_schema.tables t
            JOIN pg_class c ON c.relname = t.table_name
            JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = t.table_schema
            WHERE t.table_type = 'BASE TABLE'
              AND t.table_schema = ANY($1)
            ORDER BY t.table_schema, t.table_name
        """
        schema_names = list(db_map.schemas.keys())
        records = await conn.fetch(sql, schema_names)

        for record in records:
            schema_name = record["table_schema"]
            table_name = record["table_name"]

            if schema_name in db_map.schemas:
                db_map.schemas[schema_name].tables[table_name] = TableInfo(
                    schema=schema_name,
                    name=table_name,
                    comment=record["comment"],
                    row_estimate=record["row_estimate"],
                    size=record["size"],
                )

    async def _discover_columns(self, conn, db_map: DatabaseMap) -> None:
        """Descobre colunas de cada tabela."""
        sql = """
            SELECT
                c.table_schema,
                c.table_name,
                c.column_name,
                c.data_type,
                c.is_nullable = 'YES' AS is_nullable,
                c.column_default AS default_value,
                CASE WHEN pk.column_name IS NOT NULL THEN TRUE ELSE FALSE END AS is_pk
            FROM information_schema.columns c
            LEFT JOIN (
                SELECT ku.table_schema, ku.table_name, ku.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage ku
                  ON tc.constraint_name = ku.constraint_name
                 AND tc.constraint_schema = ku.constraint_schema
                 AND tc.table_schema = ku.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
            ) pk ON c.table_schema = pk.table_schema
                AND c.table_name = pk.table_name
                AND c.column_name = pk.column_name
            WHERE c.table_schema = ANY($1)
            ORDER BY c.table_schema, c.table_name, c.ordinal_position
        """
        schema_names = list(db_map.schemas.keys())
        records = await conn.fetch(sql, schema_names)

        for record in records:
            schema_name = record["table_schema"]
            table_name = record["table_name"]

            schema = db_map.schemas.get(schema_name)
            if schema and table_name in schema.tables:
                column = ColumnInfo(
                    name=record["column_name"],
                    data_type=record["data_type"],
                    is_nullable=record["is_nullable"],
                    default_value=record["default_value"],
                    is_primary_key=record["is_pk"],
                )
                schema.tables[table_name].columns[column.name] = column

    async def _discover_comments(self, conn, db_map: DatabaseMap) -> None:
        """Descobre comentários de colunas."""
        sql = """
            SELECT
                c.table_schema,
                c.table_name,
                c.column_name,
                pgd.description AS comment
            FROM pg_catalog.pg_statio_all_tables AS st
            INNER JOIN pg_catalog.pg_description pgd
                ON pgd.objoid = st.relid
            INNER JOIN information_schema.columns c
                ON pgd.objsubid = c.ordinal_position
                AND c.table_schema = st.schemaname
                AND c.table_name = st.relname
            WHERE c.table_schema = ANY($1)
        """
        schema_names = list(db_map.schemas.keys())
        records = await conn.fetch(sql, schema_names)

        for record in records:
            schema_name = record["table_schema"]
            table_name = record["table_name"]
            column_name = record["column_name"]

            schema = db_map.schemas.get(schema_name)
            if schema:
                table = schema.tables.get(table_name)
                if table and column_name in table.columns:
                    table.columns[column_name].comment = record["comment"]

    async def _discover_foreign_keys(self, conn, db_map: DatabaseMap) -> None:
        """Descobre chaves estrangeiras."""
        sql = """
            SELECT
                tc.table_schema,
                tc.table_name,
                ku.column_name,
                ccu.table_schema AS ref_schema,
                ccu.table_name AS ref_table,
                ccu.column_name AS ref_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage ku
              ON tc.constraint_name = ku.constraint_name
             AND tc.constraint_schema = ku.constraint_schema
             AND tc.table_schema = ku.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON tc.constraint_name = ccu.constraint_name
             AND tc.constraint_schema = ccu.constraint_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = ANY($1)
        """
        schema_names = list(db_map.schemas.keys())
        records = await conn.fetch(sql, schema_names)

        for record in records:
            schema_name = record["table_schema"]
            table_name = record["table_name"]

            schema = db_map.schemas.get(schema_name)
            if schema:
                table = schema.tables.get(table_name)
                if table:
                    table.foreign_keys.append({
                        "column": record["column_name"],
                        "ref_schema": record["ref_schema"],
                        "ref_table": record["ref_table"],
                        "ref_column": record["ref_column"],
                    })

    async def _discover_indexes(self, conn, db_map: DatabaseMap) -> None:
        """Descobre índices."""
        sql = """
            SELECT
                schemaname AS table_schema,
                tablename AS table_name,
                indexname AS index_name,
                indexdef AS definition
            FROM pg_indexes
            WHERE schemaname = ANY($1)
            ORDER BY schemaname, tablename, indexname
        """
        schema_names = list(db_map.schemas.keys())
        records = await conn.fetch(sql, schema_names)

        for record in records:
            schema_name = record["table_schema"]
            table_name = record["table_name"]

            schema = db_map.schemas.get(schema_name)
            if schema:
                table = schema.tables.get(table_name)
                if table:
                    table.indexes.append({
                        "name": record["index_name"],
                        "definition": record["definition"],
                    })

    def get_map(self, alias: str) -> Optional[DatabaseMap]:
        """Obtém o mapa de um banco específico."""
        return self._maps.get(alias)

    def get_all_maps(self) -> dict[str, DatabaseMap]:
        """Obtém todos os mapas."""
        return self._maps.copy()


# Instância global do serviço de descoberta
discovery_service = DiscoveryService()
