from __future__ import annotations

import uvicorn
from fastapi import FastAPI

from .api import create_api_router
from .application import create_orchestration_service
from .config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    service = create_orchestration_service(settings or Settings())
    app = FastAPI(title="MCP Orchestrator", version="0.1.0")
    app.state.orchestration_service = service
    app.include_router(create_api_router(service))
    return app


app = create_app()


def run() -> None:
    uvicorn.run("mcp_orchestrator.main:app", host="127.0.0.1", port=8000, reload=False)
