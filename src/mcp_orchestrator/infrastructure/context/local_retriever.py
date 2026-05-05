from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp_orchestrator.domain.enums import DocumentType, Domain
from mcp_orchestrator.domain.models import RetrievedContext, RetrievedContextItem

from .chunking import chunk_text
from .document_loader import LoadedDocument, LocalDocumentLoader


@dataclass(frozen=True)
class IndexedChunk:
    document: LoadedDocument
    content: str
    tokens: set[str]


class LocalContextRetriever:
    required_business_rule_fields = (
        "Rule ID",
        "Domain",
        "Tags",
        "Applies To",
        "Business Definition",
        "Data Sources",
        "SQL/DAX Guidance",
        "Validation Notes",
        "Owner",
        "Last Reviewed",
    )

    def __init__(self, docs_dir: Path, *, chunk_size: int = 900) -> None:
        self.docs_dir = docs_dir
        self.chunk_size = chunk_size
        self.documents: list[LoadedDocument] = []
        self.chunks: list[IndexedChunk] = []
        self.rebuild()

    def rebuild(self) -> None:
        loader = LocalDocumentLoader(self.docs_dir)
        self.documents = loader.load()
        self.chunks = [
            IndexedChunk(document=document, content=chunk, tokens=self._tokens(chunk))
            for document in self.documents
            for chunk in chunk_text(document.content, self.chunk_size)
        ]

    def status(self) -> dict[str, Any]:
        return {
            "docs_dir": str(self.docs_dir),
            "document_count": len(self.documents),
            "chunk_count": len(self.chunks),
            "business_rules": self._business_rules_status(),
        }

    def retrieve(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> RetrievedContext:
        filters = filters or {}
        query_tokens = self._tokens(query)
        candidates = [chunk for chunk in self.chunks if self._matches_filters(chunk, filters)]
        scored = [(self._score(query_tokens, chunk), chunk) for chunk in candidates]
        scored.sort(key=lambda item: item[0], reverse=True)

        items = [
            RetrievedContextItem(
                source_path=str(chunk.document.source_path),
                document_type=chunk.document.document_type,
                domain=chunk.document.domain,
                tags=chunk.document.tags,
                content=chunk.content,
                score=score,
            )
            for score, chunk in scored[:limit]
            if score > 0
        ]

        return RetrievedContext(
            query=query,
            items=items,
            filters=filters,
            total_candidates=len(candidates),
        )

    def _matches_filters(self, chunk: IndexedChunk, filters: dict[str, Any]) -> bool:
        domain = filters.get("domain")
        if domain and chunk.document.domain and self._enum_value(chunk.document.domain) != self._enum_value(domain):
            return False

        document_type = filters.get("document_type")
        if document_type and self._enum_value(chunk.document.document_type) != self._enum_value(document_type):
            return False

        tags = filters.get("tags") or []
        if tags:
            requested = {str(tag).lower() for tag in tags}
            if not requested.intersection(chunk.document.tags):
                return False

        return True

    def _score(self, query_tokens: set[str], chunk: IndexedChunk) -> float:
        if not query_tokens:
            return 0.0
        overlap = query_tokens.intersection(chunk.tokens)
        if not overlap:
            return 0.0
        score = len(overlap) / len(query_tokens)
        if "schema" in query_tokens and chunk.document.document_type == DocumentType.SCHEMA:
            score += 0.1
        if "rule" in query_tokens and chunk.document.document_type == DocumentType.BUSINESS_RULE:
            score += 0.1
        return round(score, 4)

    def _tokens(self, text: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-zA-Z0-9_]+", text.lower())
            if len(token) > 2
        }

    def _enum_value(self, value: Any) -> str:
        if isinstance(value, Domain | DocumentType):
            return value.value
        return str(value)

    def _business_rules_status(self) -> dict[str, Any]:
        rules = [
            document
            for document in self.documents
            if document.document_type == DocumentType.BUSINESS_RULE
        ]
        validations = [self._validate_business_rule(document) for document in rules]
        invalid = [item for item in validations if item["missing_fields"]]
        return {
            "required_fields": list(self.required_business_rule_fields),
            "rule_count": len(rules),
            "valid_count": len(validations) - len(invalid),
            "invalid_count": len(invalid),
            "rules": validations,
        }

    def _validate_business_rule(self, document: LoadedDocument) -> dict[str, Any]:
        found = {
            line.split(":", 1)[0].strip()
            for line in document.content.splitlines()
            if ":" in line and not line.startswith("#")
        }
        missing = [
            field
            for field in self.required_business_rule_fields
            if field not in found
        ]
        return {
            "source_path": str(document.source_path),
            "domain": document.domain.value if document.domain else None,
            "tags": document.tags,
            "missing_fields": missing,
            "valid": not missing,
        }


TextualRagRetriever = LocalContextRetriever
