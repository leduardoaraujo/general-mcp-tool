"""
RAG Service (Retrieval-Augmented Generation)

Sistema opcional de recuperação semântica para enriquecer
o entendimento do domínio através de embeddings.

Requer instalação opcional:
    pip install sentence-transformers pgvector

Este módulo é opcional - o servidor funciona sem ele,
mas com capacidades de busca semântica reduzidas.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.services.discovery import DatabaseMap

logger = logging.getLogger(__name__)

# Flag para verificar se RAG está disponível
RAG_AVAILABLE = False

try:
    # Tenta importar dependências opcionais
    import numpy as np
    RAG_AVAILABLE = True
except ImportError:
    logger.debug("NumPy not available - RAG features limited")


try:
    from sentence_transformers import SentenceTransformer
    RAG_AVAILABLE = True
except ImportError:
    logger.debug("sentence-transformers not available - RAG disabled")


@dataclass
class IndexedDocument:
    """Documento indexado para busca vetorial."""

    id: str
    content: str
    doc_type: str  # 'table', 'column', 'query_example', 'glossary'
    source: str  # 'schema', 'user_defined', etc.
    metadata: dict
    embedding: Optional[list[float]] = None


class SimpleVectorStore:
    """
    Armazenamento vetorial simples em memória.

    Para produção, considere usar pgvector ou FAISS.
    """

    def __init__(self):
        self.documents: dict[str, IndexedDocument] = {}
        self.embeddings: dict[str, list[float]] = {}

    def add(self, doc: IndexedDocument) -> None:
        """Adiciona um documento ao índice."""
        self.documents[doc.id] = doc
        if doc.embedding:
            self.embeddings[doc.id] = doc.embedding

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        doc_type: Optional[str] = None,
    ) -> list[tuple[IndexedDocument, float]]:
        """
        Busca documentos similares.

        Args:
            query_embedding: Embedding da consulta
            top_k: Número de resultados
            doc_type: Filtrar por tipo de documento

        Returns:
            Lista de (documento, score) ordenada por relevância
        """
        if not RAG_AVAILABLE or not self.embeddings:
            return []

        try:
            import numpy as np

            query_vec = np.array(query_embedding)
            results = []

            for doc_id, embedding in self.embeddings.items():
                doc = self.documents.get(doc_id)
                if not doc:
                    continue

                # Filtro por tipo
                if doc_type and doc.doc_type != doc_type:
                    continue

                # Calcula similaridade cosseno
                doc_vec = np.array(embedding)
                similarity = np.dot(query_vec, doc_vec) / (
                    np.linalg.norm(query_vec) * np.linalg.norm(doc_vec)
                )
                results.append((doc, float(similarity)))

            # Ordena por similaridade decrescente
            results.sort(key=lambda x: x[1], reverse=True)
            return results[:top_k]

        except Exception as e:
            logger.warning(f"Vector search failed: {e}")
            return []


class RAGService:
    """
    Serviço de RAG para enriquecimento semântico.

    Indexa e permite busca sobre:
    - Descrições de tabelas
    - Comentários de colunas
    - Exemplos de queries
    - Glossário de negócio
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.model: Optional["SentenceTransformer"] = None
        self.vector_store = SimpleVectorStore()
        self._initialized = False

    def is_available(self) -> bool:
        """Verifica se o serviço RAG está disponível."""
        return RAG_AVAILABLE

    async def initialize(self) -> bool:
        """Inicializa o modelo de embeddings."""
        if not RAG_AVAILABLE:
            logger.info("RAG dependencies not available - RAG disabled")
            return False

        if self._initialized:
            return True

        try:
            logger.info(f"Loading embedding model: {self.model_name}")
            self.model = SentenceTransformer(self.model_name)
            self._initialized = True
            logger.info("RAG service initialized successfully")
            return True
        except Exception as e:
            logger.warning(f"Failed to initialize RAG: {e}")
            return False

    def _encode(self, text: str) -> list[float]:
        """Codifica texto em embedding."""
        if not self.model:
            return []
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.tolist()

    def index_schema(self, db_map: "DatabaseMap") -> None:
        """Indexa o schema do banco de dados."""
        if not self._initialized:
            return

        logger.info(f"Indexing schema from {db_map.database_alias}")
        count = 0

        for schema_name, schema in db_map.schemas.items():
            for table_name, table in schema.tables.items():
                # Indexa descrição da tabela
                if table.comment:
                    doc = IndexedDocument(
                        id=f"table:{schema_name}.{table_name}",
                        content=f"Table {schema_name}.{table_name}: {table.comment}",
                        doc_type="table",
                        source="schema",
                        metadata={
                            "schema": schema_name,
                            "table": table_name,
                            "row_estimate": table.row_estimate,
                        },
                        embedding=self._encode(f"{table_name} {table.comment}"),
                    )
                    self.vector_store.add(doc)
                    count += 1

                # Indexa colunas
                for col_name, col in table.columns.items():
                    if col.comment:
                        doc = IndexedDocument(
                            id=f"column:{schema_name}.{table_name}.{col_name}",
                            content=(
                                f"Column {col_name} in {schema_name}.{table_name} "
                                f"({col.data_type}): {col.comment}"
                            ),
                            doc_type="column",
                            source="schema",
                            metadata={
                                "schema": schema_name,
                                "table": table_name,
                                "column": col_name,
                                "data_type": col.data_type,
                            },
                            embedding=self._encode(f"{col_name} {col.comment} {table_name}"),
                        )
                        self.vector_store.add(doc)
                        count += 1

        logger.info(f"Indexed {count} documents from schema")

    def add_query_example(
        self,
        question: str,
        sql: str,
        description: str = "",
    ) -> None:
        """Adiciona um exemplo de query ao índice."""
        if not self._initialized:
            return

        doc_id = f"example:{hash(question + sql) % 10000000}"
        doc = IndexedDocument(
            id=doc_id,
            content=f"Question: {question}\nSQL: {sql}\nDescription: {description}",
            doc_type="query_example",
            source="user_defined",
            metadata={
                "question": question,
                "sql": sql,
                "description": description,
            },
            embedding=self._encode(f"{question} {description}"),
        )
        self.vector_store.add(doc)

    def add_glossary_term(
        self,
        term: str,
        definition: str,
        related_tables: Optional[list[str]] = None,
    ) -> None:
        """Adiciona um termo ao glossário de negócio."""
        if not self._initialized:
            return

        doc_id = f"glossary:{term.lower().replace(' ', '_')}"
        doc = IndexedDocument(
            id=doc_id,
            content=f"Term: {term}\nDefinition: {definition}",
            doc_type="glossary",
            source="business_glossary",
            metadata={
                "term": term,
                "definition": definition,
                "related_tables": related_tables or [],
            },
            embedding=self._encode(f"{term} {definition}"),
        )
        self.vector_store.add(doc)

    def search(
        self,
        query: str,
        top_k: int = 5,
        doc_type: Optional[str] = None,
    ) -> list[dict]:
        """
        Busca documentos relevantes.

        Args:
            query: Texto de consulta
            top_k: Número de resultados
            doc_type: Filtrar por tipo

        Returns:
            Lista de resultados com documento e score
        """
        if not self._initialized or not self.model:
            return []

        query_embedding = self._encode(query)
        results = self.vector_store.search(query_embedding, top_k, doc_type)

        return [
            {
                "id": doc.id,
                "type": doc.doc_type,
                "content": doc.content,
                "metadata": doc.metadata,
                "score": round(score, 4),
            }
            for doc, score in results
        ]

    def find_similar_queries(self, question: str, top_k: int = 3) -> list[dict]:
        """Busca queries similares já feitas."""
        return self.search(question, top_k, doc_type="query_example")

    def find_relevant_tables(self, question: str, top_k: int = 5) -> list[dict]:
        """Busca tabelas relevantes para uma pergunta."""
        return self.search(question, top_k, doc_type="table")


# Instância global
rag_service = RAGService()
