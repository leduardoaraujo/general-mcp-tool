from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .api import create_api_router
from .application import create_orchestration_service
from .config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    service = create_orchestration_service(settings or Settings())
    app = FastAPI(title="MCP Orchestrator", version="0.1.0")
    app.state.orchestration_service = service
    app.include_router(create_api_router(service))
    ui_dir = Path(__file__).resolve().parent / "ui" / "static"
    if ui_dir.exists():
        app.mount("/static", StaticFiles(directory=ui_dir), name="static")

        @app.get("/", include_in_schema=False)
        @app.get("/chat-ui", include_in_schema=False)
        async def chat_ui() -> FileResponse:
            return FileResponse(ui_dir / "index.html")

        @app.get("/favicon.ico", include_in_schema=False)
        async def favicon() -> Response:
            return Response(status_code=204)

    return app


app = create_app()


def run() -> None:
    uvicorn.run("mcp_orchestrator.main:app", host="127.0.0.1", port=8000, reload=False)
