from pathlib import Path

from mcp_orchestrator.domain.enums import DocumentType
from mcp_orchestrator.infrastructure.context import LocalContextRetriever


def test_retriever_loads_documents_and_returns_relevant_chunk() -> None:
    retriever = LocalContextRetriever(Path("docs/context"))
    result = retriever.retrieve("sales_orders revenue schema")

    assert retriever.status()["document_count"] >= 1
    assert result.items
    assert result.items[0].document_type == DocumentType.SCHEMA
    assert "sales_orders" in result.items[0].content


def test_retriever_filters_by_document_type() -> None:
    retriever = LocalContextRetriever(Path("docs/context"))
    result = retriever.retrieve(
        "confirmed revenue",
        filters={"document_type": DocumentType.BUSINESS_RULE},
    )

    assert result.items
    assert all(item.document_type == DocumentType.BUSINESS_RULE for item in result.items)
