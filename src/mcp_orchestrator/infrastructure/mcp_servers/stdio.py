from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from mcp_orchestrator.domain.models import (
    McpToolCallResponse,
    McpToolDefinition,
)

from .catalog import McpServerDefinition


class StdioMcpToolRunner:
    async def list_tools(self, server: McpServerDefinition) -> list[McpToolDefinition]:
        async with self._session(server) as session:
            result = await session.list_tools()
            return [
                McpToolDefinition(
                    name=tool.name,
                    description=getattr(tool, "description", None),
                    input_schema=self._schema(tool),
                )
                for tool in result.tools
            ]

    async def call_tool(
        self,
        server: McpServerDefinition,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> McpToolCallResponse:
        async with self._session(server) as session:
            result = await session.call_tool(tool_name, arguments or {})
            return McpToolCallResponse(
                server_name=server.name,
                tool_name=tool_name,
                is_error=bool(getattr(result, "isError", False)),
                content=self._content_text(result),
                structured_content=getattr(result, "structuredContent", None),
                raw_result=self._dump(result),
            )

    def _session(self, server: McpServerDefinition):
        params = StdioServerParameters(
            command=server.command,
            args=server.args,
            cwd=Path(server.path),
        )
        return _ClientSessionContext(params)

    def _schema(self, tool: Any) -> dict[str, Any]:
        schema = getattr(tool, "inputSchema", None)
        if isinstance(schema, dict):
            return schema
        if hasattr(schema, "model_dump"):
            return schema.model_dump(mode="json")
        return {}

    def _content_text(self, result: Any) -> list[str]:
        content = getattr(result, "content", []) or []
        return [
            str(getattr(item, "text", item))
            for item in content
        ]

    def _dump(self, value: Any) -> dict[str, Any]:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json", by_alias=True)
        if isinstance(value, dict):
            return value
        return {"repr": repr(value)}


class _ClientSessionContext:
    def __init__(self, params: StdioServerParameters) -> None:
        self.params = params
        self._stdio_context = None
        self._session_context = None

    async def __aenter__(self) -> ClientSession:
        self._stdio_context = stdio_client(self.params)
        read_stream, write_stream = await self._stdio_context.__aenter__()
        self._session_context = ClientSession(read_stream, write_stream)
        session = await self._session_context.__aenter__()
        await session.initialize()
        return session

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session_context is not None:
            await self._session_context.__aexit__(exc_type, exc, tb)
        if self._stdio_context is not None:
            await self._stdio_context.__aexit__(exc_type, exc, tb)
