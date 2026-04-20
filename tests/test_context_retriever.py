from pathlib import Path

from mcp_orchestrator.domain.enums import DocumentType
from mcp_orchestrator.infrastructure.context import LocalContextRetriever


def test_context_retriever_loads_docs_context() -> None:
    retriever = LocalContextRetriever(Path("docs/context"))

    status = retriever.status()

    assert status["document_count"] >= 5
    assert status["chunk_count"] >= 5


def test_context_retriever_detects_required_document_types() -> None:
    retriever = LocalContextRetriever(Path("docs/context"))

    document_types = {document.document_type for document in retriever.documents}

    assert DocumentType.BUSINESS_RULE in document_types
    assert DocumentType.SCHEMA in document_types
    assert DocumentType.TECHNICAL_DOC in document_types
    assert DocumentType.EXAMPLE in document_types
    assert DocumentType.PLAYBOOK in document_types


def test_context_retriever_scores_and_filters_postgresql_context() -> None:
    retriever = LocalContextRetriever(Path("docs/context"))

    result = retriever.retrieve(
        "postgresql monthly sales revenue",
        filters={"tags": ["postgresql"]},
    )

    assert result.items
    assert all("postgresql" in item.tags for item in result.items)
    assert result.items[0].score > 0
