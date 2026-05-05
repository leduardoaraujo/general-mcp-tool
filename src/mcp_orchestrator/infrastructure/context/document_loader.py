from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from mcp_orchestrator.domain.enums import DocumentType, Domain


@dataclass(frozen=True)
class LoadedDocument:
    source_path: Path
    content: str
    document_type: DocumentType
    domain: Domain | None
    tags: list[str]


class LocalDocumentLoader:
    supported_suffixes = {".md", ".txt"}

    def __init__(self, docs_dir: Path) -> None:
        self.docs_dir = docs_dir

    def load(self) -> list[LoadedDocument]:
        if not self.docs_dir.exists():
            return []

        documents: list[LoadedDocument] = []
        for path in sorted(self.docs_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in self.supported_suffixes:
                continue
            content = path.read_text(encoding="utf-8")
            documents.append(
                LoadedDocument(
                    source_path=path,
                    content=content,
                    document_type=self._document_type(path),
                    domain=self._domain(path, content),
                    tags=self._tags(path, content),
                )
            )
        return documents

    def _document_type(self, path: Path) -> DocumentType:
        parts = {part.lower() for part in path.parts}
        if "business_rules" in parts:
            return DocumentType.BUSINESS_RULE
        if "schemas" in parts:
            return DocumentType.SCHEMA
        if "technical_docs" in parts:
            return DocumentType.TECHNICAL_DOC
        if "playbooks" in parts:
            return DocumentType.PLAYBOOK
        if "examples" in parts:
            return DocumentType.EXAMPLE
        return DocumentType.UNKNOWN

    def _domain(self, path: Path, content: str) -> Domain | None:
        declared_domain = self._declared_domain(content)
        if declared_domain:
            return declared_domain

        text = f"{path.as_posix()} {content}".lower()
        if "power bi" in text or "dax" in text or "semantic model" in text:
            return Domain.POWER_BI
        if "postgres" in text or "postgresql" in text:
            return Domain.POSTGRESQL
        if "sql server" in text or "mssql" in text:
            return Domain.SQL_SERVER
        if "excel" in text or "xlsx" in text or "spreadsheet" in text:
            return Domain.EXCEL
        if "sales" in text or "analytics" in text:
            return Domain.ANALYTICS
        return None

    def _declared_domain(self, content: str) -> Domain | None:
        for line in content.splitlines():
            if not line.lower().startswith("domain:"):
                continue
            value = line.split(":", 1)[1].strip().lower().replace("-", "_")
            for domain in Domain:
                if value == domain.value:
                    return domain
        return None

    def _tags(self, path: Path, content: str) -> list[str]:
        tags = {path.stem.lower()}
        for line in content.splitlines():
            if line.lower().startswith("tags:"):
                raw_tags = line.split(":", 1)[1]
                tags.update(tag.strip().lower() for tag in raw_tags.split(",") if tag.strip())
            if line.startswith("#"):
                heading = re.sub(r"^#+", "", line).strip().lower()
                tags.update(word for word in re.findall(r"[a-z0-9_]+", heading) if len(word) > 2)
        return sorted(tags)
