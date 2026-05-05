from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP


DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT_SECONDS = 60.0
POWERBI_MCP_SERVER_NAME = "power_bi"
POWERBI_TOOL_NAMES = [
    "database_operations",
    "trace_operations",
    "named_expression_operations",
    "measure_operations",
    "object_translation_operations",
    "dax_query_operations",
    "perspective_operations",
    "column_operations",
    "user_hierarchy_operations",
    "calculation_group_operations",
    "security_role_operations",
    "table_operations",
    "calendar_operations",
    "relationship_operations",
    "model_operations",
    "culture_operations",
    "function_operations",
    "query_group_operations",
    "transaction_operations",
    "connection_operations",
    "partition_operations",
]


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
        confirmation_id: str | None = None,
        include_debug: bool = False,
    ) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        if allow_execution:
            metadata["allow_execution"] = True
        if confirmation_id:
            metadata["confirmation_id"] = confirmation_id

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

    async def execute_confirmation(
        self,
        confirmation_id: str,
        *,
        include_debug: bool = False,
    ) -> dict[str, Any]:
        result = await self._request("POST", f"/confirmations/{confirmation_id}/execute")
        if not result["ok"]:
            return result
        data = result["data"]
        response = data.get("response", {})
        if isinstance(response, dict):
            formatted = self._format_orchestrate_response(response, include_debug=include_debug)
        else:
            formatted = {"ok": False, "error": "Invalid confirmation response."}
        formatted["confirmation_id"] = data.get("confirmation_id", confirmation_id)
        formatted["confirmation_status"] = data.get("status")
        return formatted

    async def call_powerbi_tool(
        self,
        tool_name: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        if tool_name not in POWERBI_TOOL_NAMES:
            return {
                "ok": False,
                "api_url": self.settings.api_url,
                "error": f"Unsupported Power BI MCP tool: {tool_name}",
                "supported_tools": POWERBI_TOOL_NAMES,
            }

        result = await self._request(
            "POST",
            f"/mcp-servers/{POWERBI_MCP_SERVER_NAME}/tools/{tool_name}",
            json={"arguments": {"request": request}},
        )
        if not result["ok"]:
            return result

        data = result["data"]
        is_error = bool(data.get("is_error", False))
        return {
            "ok": not is_error,
            "api_url": self.settings.api_url,
            "server_name": data.get("server_name"),
            "tool_name": data.get("tool_name"),
            "is_error": is_error,
            "content": data.get("content", []),
            "structured_content": data.get("structured_content"),
            "raw_result": data.get("raw_result", {}),
        }

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
            "confirmation_id": data.get("confirmation_id"),
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
        confirmation_id: str | None = None,
        include_debug: bool = False,
    ) -> dict[str, Any]:
        """Send a contextual request to the MCP Orchestrator API."""
        return await proxy_client.ask(
            message=message,
            domain_hint=domain_hint,
            tags=tags,
            allow_execution=allow_execution,
            confirmation_id=confirmation_id,
            include_debug=include_debug,
        )

    @server.tool()
    async def execute_confirmation(
        confirmation_id: str,
        include_debug: bool = False,
    ) -> dict[str, Any]:
        """Execute a pending read-only confirmation through the MCP Orchestrator API."""
        return await proxy_client.execute_confirmation(
            confirmation_id,
            include_debug=include_debug,
        )

    for tool_name in POWERBI_TOOL_NAMES:
        server.add_tool(
            _build_powerbi_proxy_tool(proxy_client, tool_name),
            name=f"powerbi_{tool_name}",
            description=(
                f"Proxy for Power BI MCP `{tool_name}`. Pass the inner "
                "`request` object expected by the Microsoft Power BI Modeling MCP tool."
            ),
        )

    return server


def _build_powerbi_proxy_tool(
    proxy_client: OrchestratorProxyClient,
    tool_name: str,
):
    async def powerbi_tool(request: dict[str, Any]) -> dict[str, Any]:
        return await proxy_client.call_powerbi_tool(tool_name, request)

    powerbi_tool.__name__ = f"powerbi_{tool_name}"
    powerbi_tool.__doc__ = (
        f"Call Power BI MCP tool `{tool_name}` through the orchestrator API."
    )
    return powerbi_tool


def run() -> None:
    create_mcp_server().run(transport="stdio")


if __name__ == "__main__":
    run()


__all__ = [
    "OrchestratorProxyClient",
    "OrchestratorProxySettings",
    "POWERBI_TOOL_NAMES",
    "create_mcp_server",
    "run",
]
