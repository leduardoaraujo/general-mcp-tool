from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP


DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class OrchestratorProxySettings:
    api_url: str = DEFAULT_API_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> "OrchestratorProxySettings":
        timeout_value = os.getenv("MCP_ORCHESTRATOR_TIMEOUT_SECONDS", "")
        try:
            timeout_seconds = float(timeout_value) if timeout_value else DEFAULT_TIMEOUT_SECONDS
        except ValueError:
            timeout_seconds = DEFAULT_TIMEOUT_SECONDS

        return cls(
            api_url=os.getenv("MCP_ORCHESTRATOR_API_URL", DEFAULT_API_URL).rstrip("/"),
            timeout_seconds=timeout_seconds,
        )


class OrchestratorProxyClient:
    def __init__(
        self,
        settings: OrchestratorProxySettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or OrchestratorProxySettings.from_env()
        self._transport = transport

    async def health(self) -> dict[str, Any]:
        result = await self._request("GET", "/health")
        if result["ok"]:
            return {
                "ok": True,
                "api_url": self.settings.api_url,
                "status": result["data"].get("status"),
                "service": result["data"].get("service"),
                "data": result["data"],
            }
        return result

    async def ask(
        self,
        *,
        message: str,
        domain_hint: str | None = None,
        tags: list[str] | None = None,
        allow_execution: bool = False,
        include_debug: bool = False,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        if allow_execution:
            metadata["allow_execution"] = True

        payload = {
            "message": message,
            "domain_hint": domain_hint,
            "tags": tags or [],
            "metadata": metadata,
        }
        result = await self._request("POST", "/orchestrate", json=payload)
        if not result["ok"]:
            return result
        return self._format_orchestrate_response(result["data"], include_debug=include_debug)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self.settings.api_url,
                timeout=self.settings.timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.request(method, path, json=json)
        except httpx.RequestError as exc:
            return {
                "ok": False,
                "api_url": self.settings.api_url,
                "error": f"Orchestrator API unavailable at {self.settings.api_url}",
                "detail": str(exc),
            }

        try:
            data = response.json()
        except ValueError:
            data = {"raw_body": response.text}

        if response.is_error:
            return {
                "ok": False,
                "api_url": self.settings.api_url,
                "status_code": response.status_code,
                "error": self._extract_error_detail(data),
                "detail": data,
            }

        return {
            "ok": True,
            "api_url": self.settings.api_url,
            "status_code": response.status_code,
            "data": data,
        }

    def _format_orchestrate_response(
        self,
        data: dict[str, Any],
        *,
        include_debug: bool,
    ) -> dict[str, Any]:
        formatted = {
            "ok": True,
            "api_url": self.settings.api_url,
            "correlation_id": data.get("correlation_id"),
            "status": data.get("status"),
            "summary": data.get("summary"),
            "structured_data": data.get("structured_data"),
            "sources_used": data.get("sources_used", []),
            "warnings": data.get("warnings", []),
            "errors": data.get("errors", []),
            "next_actions": data.get("next_actions", []),
            "specialist_results": data.get("specialist_results", []),
            "mcp_trace": data.get("mcp_trace", []),
            "timings": data.get("timings", {}),
        }
        if include_debug:
            formatted["debug"] = data.get("debug", {})
        return formatted

    def _extract_error_detail(self, data: Any) -> str:
        if isinstance(data, dict):
            detail = data.get("detail")
            if isinstance(detail, str):
                return detail
            if detail is not None:
                return str(detail)
            raw_body = data.get("raw_body")
            if isinstance(raw_body, str):
                return raw_body
        return "Orchestrator API request failed"


def create_mcp_server(
    client: OrchestratorProxyClient | None = None,
) -> FastMCP:
    proxy_client = client or OrchestratorProxyClient()
    server = FastMCP(
        "mcp-orchestrator-proxy",
        instructions=(
            "Proxy MCP server for the local MCP Orchestrator FastAPI service. "
            "Start the orchestrator API before using these tools."
        ),
    )

    @server.tool()
    async def orchestrator_health() -> dict[str, Any]:
        """Check whether the local MCP Orchestrator API is reachable."""
        return await proxy_client.health()

    @server.tool()
    async def ask_orchestrator(
        message: str,
        domain_hint: str | None = None,
        tags: list[str] | None = None,
        allow_execution: bool = False,
        include_debug: bool = False,
    ) -> dict[str, Any]:
        """Send a contextual request to the MCP Orchestrator API."""
        return await proxy_client.ask(
            message=message,
            domain_hint=domain_hint,
            tags=tags,
            allow_execution=allow_execution,
            include_debug=include_debug,
        )

    return server


def run() -> None:
    create_mcp_server().run(transport="stdio")


if __name__ == "__main__":
    run()


__all__ = [
    "OrchestratorProxyClient",
    "OrchestratorProxySettings",
    "create_mcp_server",
    "run",
]
