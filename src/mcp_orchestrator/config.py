from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    project_dir: Path = Path.cwd()
    docs_dir: Path | None = None
    rag_chunk_size: int = 900
    rag_top_k: int = 5

    def resolved_project_dir(self) -> Path:
        return Path(os.getenv("MCP_ORCHESTRATOR_PROJECT_DIR", self.project_dir)).resolve()

    def resolved_docs_dir(self) -> Path:
        configured = os.getenv("MCP_ORCHESTRATOR_DOCS_DIR")
        if configured:
            return Path(configured).resolve()
        if self.docs_dir:
            return self.docs_dir.resolve()
        return self.resolved_project_dir() / "docs"
