from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    project_dir: Path = Path.cwd()
    docs_dir: Path | None = None
    mcps_dir: Path | None = None
    audit_db_path: Path | None = None
    rag_chunk_size: int = 900
    rag_top_k: int = 5
    intelligence_mode: str | None = None
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"

    def resolved_project_dir(self) -> Path:
        return Path(os.getenv("MCP_ORCHESTRATOR_PROJECT_DIR", self.project_dir)).resolve()

    def resolved_docs_dir(self) -> Path:
        configured = os.getenv("MCP_ORCHESTRATOR_DOCS_DIR")
        if configured:
            return Path(configured).resolve()
        if self.docs_dir:
            return self.docs_dir.resolve()
        return self.resolved_project_dir() / "docs" / "context"

    def resolved_mcps_dir(self) -> Path:
        configured = os.getenv("MCP_ORCHESTRATOR_MCPS_DIR")
        if configured:
            return Path(configured).resolve()
        if self.mcps_dir:
            return self.mcps_dir.resolve()
        return self.resolved_project_dir() / "mcps"

    def resolved_audit_db_path(self) -> Path:
        configured = os.getenv("MCP_ORCHESTRATOR_AUDIT_DB")
        if configured:
            return Path(configured).resolve()
        if self.audit_db_path:
            return self.audit_db_path.resolve()
        return self.resolved_project_dir() / "data" / "orchestrator.sqlite3"

    def resolved_intelligence_mode(self) -> str:
        configured = os.getenv("MCP_ORCHESTRATOR_INTELLIGENCE_MODE")
        return (configured or self.intelligence_mode or "heuristic").strip().lower()

    def resolved_openai_api_key(self) -> str | None:
        return os.getenv("OPENAI_API_KEY") or self.openai_api_key

    def resolved_openai_model(self) -> str:
        return os.getenv("OPENAI_MODEL") or self.openai_model
