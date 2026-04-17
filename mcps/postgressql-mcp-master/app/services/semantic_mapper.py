"""
Semantic Mapping Service

Mapeia termos humanos (sinônimos, conceitos) para tabelas e colunas reais.
Usa heurística baseada em nomes e stemming.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# Mapeamento de sinônimos comuns em PT-BR e EN
DEFAULT_SEMANTIC_ALIASES = {
    # Pessoas / Funcionários
    "colaborador": ["employee", "funcionario", "funcionário", "pessoa", "person", "user", "usuario", "usuário"],
    "funcionario": ["employee", "colaborador", "pessoa", "person", "user", "usuario"],
    "employee": ["colaborador", "funcionario", "pessoa", "person"],
    "pessoa": ["person", "colaborador", "funcionario", "employee", "user", "usuario"],
    "person": ["pessoa", "colaborador", "funcionario", "employee", "user"],

    # Clientes
    "cliente": ["customer", "cli", "buyer", "comprador"],
    "customer": ["cliente", "cli", "buyer"],

    # Produtos
    "produto": ["product", "item", "mercadoria", "goods"],
    "product": ["produto", "item", "goods"],
    "item": ["produto", "product", "line_item"],

    # Pedidos / Vendas
    "pedido": ["order", "venda", "sale", "ordem", "compra"],
    "order": ["pedido", "venda", "sale", "ordem"],
    "venda": ["sale", "order", "pedido"],
    "sale": ["venda", "order", "pedido"],

    # Pagamentos
    "pagamento": ["payment", "pag", "pay"],
    "payment": ["pagamento", "pay"],

    # Endereços
    "endereco": ["address", "end", "addr", "localização", "location"],
    "endereço": ["address", "end", "addr", "localização", "location"],
    "address": ["endereco", "endereço", "end", "addr"],

    # Datas
    "data": ["date", "dt", "quando", "when"],
    "date": ["data", "dt", "when"],
    "created": ["criado", "criado_em", "created_at", "dt_criacao"],
    "criado": ["created", "criado_em", "created_at"],

    # Identificadores
    "id": ["codigo", "código", "code", "key", "pk", "identifier"],
    "codigo": ["id", "código", "code", "key"],
    "código": ["id", "codigo", "code", "key"],

    # Status
    "status": ["situacao", "situação", "state", "estado", "ativo", "active"],
    "situacao": ["status", "situação", "state"],
    "situação": ["status", "situacao", "state"],

    # Valores / Dinheiro
    "valor": ["value", "amount", "price", "preco", "preço", "total", "money"],
    "value": ["valor", "amount", "price"],
    "preco": ["price", "valor", "amount"],
    "preço": ["price", "valor", "amount"],
    "price": ["preco", "preço", "valor"],

    # Quantidade
    "quantidade": ["quantity", "qty", "qtd", "amount", "count", "total"],
    "quantity": ["quantidade", "qty", "qtd"],
    "qtd": ["quantidade", "quantity", "qty"],
}


@dataclass
class SemanticMatch:
    """Resultado de uma correspondência semântica."""

    term: str
    matched_table: Optional[str] = None
    matched_column: Optional[str] = None
    schema: Optional[str] = None
    confidence: float = 0.0
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "term": self.term,
            "matched_table": self.matched_table,
            "matched_column": self.matched_column,
            "schema": self.schema,
            "confidence": self.confidence,
            "reason": self.reason,
        }


class SemanticMapper:
    """
    Mapeador semântico para termos do domínio.

    Converte termos humanos (ex: "colaborador") em referências
    a tabelas/colunas reais do banco (ex: "senior.ficha_colaborador").
    """

    def __init__(self, custom_aliases: Optional[dict] = None):
        self.aliases = {**DEFAULT_SEMANTIC_ALIASES, **(custom_aliases or {})}
        self._table_cache: dict[str, list[str]] = {}
        self._column_cache: dict[str, list[tuple[str, str, str]]] = {}

    def _normalize_term(self, term: str) -> str:
        """Normaliza um termo para comparação."""
        # Remove acentos, converte para minúsculas, remove underscores
        normalized = term.lower().strip()
        normalized = re.sub(r'[_\-]', '', normalized)
        # Remove acentos comuns
        normalized = normalized.replace('á', 'a').replace('à', 'a').replace('ã', 'a').replace('â', 'a')
        normalized = normalized.replace('é', 'e').replace('ê', 'e')
        normalized = normalized.replace('í', 'i')
        normalized = normalized.replace('ó', 'o').replace('ô', 'o').replace('õ', 'o')
        normalized = normalized.replace('ú', 'u').replace('ü', 'u')
        normalized = normalized.replace('ç', 'c')
        return normalized

    def _stem(self, term: str) -> str:
        """Aplica stemming simples em português/inglês."""
        term = term.lower()
        # Remover sufixos comuns
        suffixes = ['s', 'es', 'ies', 'ção', 'ções', 'mento', 'mentos', 'a', 'o']
        for suffix in suffixes:
            if term.endswith(suffix) and len(term) > len(suffix) + 2:
                term = term[:-len(suffix)]
                break
        return term

    def register_database_schema(self, db_map) -> None:
        """
        Registra o schema do banco para mapeamento.

        Args:
            db_map: DatabaseMap do serviço de discovery
        """
        self._table_cache = {}
        self._column_cache = {}

        for schema_name, schema in db_map.schemas.items():
            for table_name, table in schema.tables.items():
                # Indexa tabela
                full_name = f"{schema_name}.{table_name}"
                table_terms = self._extract_terms(table_name)

                for term in table_terms:
                    if term not in self._table_cache:
                        self._table_cache[term] = []
                    self._table_cache[term].append(full_name)

                # Indexa colunas
                for col_name, col in table.columns.items():
                    col_terms = self._extract_terms(col_name)

                    for term in col_terms:
                        if term not in self._column_cache:
                            self._column_cache[term] = []
                        self._column_cache[term].append((schema_name, table_name, col_name))

        logger.info(
            f"Semantic mapper indexed: "
            f"{len(self._table_cache)} table terms, "
            f"{len(self._column_cache)} column terms"
        )

    def _extract_terms(self, name: str) -> list[str]:
        """Extrai termos de um nome (tabela ou coluna)."""
        terms = set()

        # Termo original
        terms.add(self._normalize_term(name))

        # Divide por underscore e camelCase
        parts = re.split(r'[_\-]+|(?<=[a-z])(?=[A-Z])', name)
        for part in parts:
            if part:
                normalized = self._normalize_term(part)
                terms.add(normalized)
                terms.add(self._stem(normalized))

        return list(terms)

    def expand_term(self, term: str) -> list[str]:
        """
        Expande um termo incluindo sinônimos.

        Args:
            term: Termo original

        Returns:
            Lista de termos relacionados
        """
        normalized = self._normalize_term(term)
        stemmed = self._stem(normalized)

        expanded = {term, normalized, stemmed}

        # Adiciona sinônimos conhecidos
        for key, synonyms in self.aliases.items():
            if normalized == self._normalize_term(key) or stemmed == self._stem(key):
                expanded.update(synonyms)
                expanded.add(key)
            elif normalized in [self._normalize_term(s) for s in synonyms]:
                expanded.update(synonyms)
                expanded.add(key)

        return list(expanded)

    def find_tables(self, term: str) -> list[SemanticMatch]:
        """
        Encontra tabelas relevantes para um termo.

        Args:
            term: Termo de busca

        Returns:
            Lista de correspondências ordenadas por confiança
        """
        matches = []
        expanded_terms = self.expand_term(term)

        for expanded_term in expanded_terms:
            # Busca exata
            if expanded_term in self._table_cache:
                for full_name in self._table_cache[expanded_term]:
                    schema, table = full_name.split('.', 1)
                    confidence = 1.0 if expanded_term == self._normalize_term(term) else 0.8
                    matches.append(SemanticMatch(
                        term=term,
                        matched_table=table,
                        schema=schema,
                        confidence=confidence,
                        reason=f"Exact match: {expanded_term}",
                    ))

            # Busca parcial
            for cached_term, tables in self._table_cache.items():
                if expanded_term in cached_term or cached_term in expanded_term:
                    for full_name in tables:
                        schema, table = full_name.split('.', 1)
                        # Evita duplicatas
                        if not any(m.matched_table == table and m.schema == schema for m in matches):
                            confidence = 0.6 if expanded_term in cached_term else 0.4
                            matches.append(SemanticMatch(
                                term=term,
                                matched_table=table,
                                schema=schema,
                                confidence=confidence,
                                reason=f"Partial match: {expanded_term} ~ {cached_term}",
                            ))

        # Ordena por confiança
        matches.sort(key=lambda m: m.confidence, reverse=True)
        return matches

    def find_columns(self, term: str, table_hint: Optional[str] = None) -> list[SemanticMatch]:
        """
        Encontra colunas relevantes para um termo.

        Args:
            term: Termo de busca
            table_hint: Nome da tabela para restringir busca (opcional)

        Returns:
            Lista de correspondências ordenadas por confiança
        """
        matches = []
        expanded_terms = self.expand_term(term)

        for expanded_term in expanded_terms:
            if expanded_term in self._column_cache:
                for schema, table, column in self._column_cache[expanded_term]:
                    # Se tem hint de tabela, prioriza
                    if table_hint:
                        table_terms = self._extract_terms(table)
                        hint_terms = self._extract_terms(table_hint)
                        if any(ht in table_terms for ht in hint_terms):
                            confidence = 1.0
                        else:
                            confidence = 0.5
                    else:
                        confidence = 0.8

                    matches.append(SemanticMatch(
                        term=term,
                        matched_table=table,
                        matched_column=column,
                        schema=schema,
                        confidence=confidence,
                        reason=f"Column match: {expanded_term}",
                    ))

        # Ordena por confiança
        matches.sort(key=lambda m: m.confidence, reverse=True)
        return matches

    def resolve_concept(self, concept: str) -> dict:
        """
        Resolve um conceito em tabelas e colunas relacionadas.

        Args:
            concept: Conceito a ser resolvido

        Returns:
            Dicionário com tabelas e colunas candidatas
        """
        tables = self.find_tables(concept)
        columns = self.find_columns(concept)

        # Remove duplicatas de tabelas já encontradas via colunas
        table_names = {(m.schema, m.matched_table) for m in tables}
        additional_tables = [
            m for m in columns
            if (m.schema, m.matched_table) not in table_names
        ]

        return {
            "concept": concept,
            "tables": [m.to_dict() for m in tables[:5]],
            "columns": [m.to_dict() for m in columns[:10]],
            "suggested_tables": list(set(
                f"{m.schema}.{m.matched_table}"
                for m in (tables + additional_tables)
            )),
        }


# Instância global
semantic_mapper = SemanticMapper()
