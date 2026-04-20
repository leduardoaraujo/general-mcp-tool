from __future__ import annotations

import os
from pathlib import Path
from types import TracebackType
from typing import Any, Awaitable, Callable

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

    async def call_tools(
        self,
        server: McpServerDefinition,
        calls: list[tuple[str, dict[str, Any] | None]],
    ) -> list[McpToolCallResponse]:
        responses: list[McpToolCallResponse] = []
        async with self._session(server) as session:
            for tool_name, arguments in calls:
                result = await session.call_tool(tool_name, arguments or {})
                responses.append(
                    McpToolCallResponse(
                        server_name=server.name,
                        tool_name=tool_name,
                        is_error=bool(getattr(result, "isError", False)),
                        content=self._content_text(result),
                        structured_content=getattr(result, "structuredContent", None),
                        raw_result=self._dump(result),
                    )
                )
        return responses

    async def call_with_session(
        self,
        server: McpServerDefinition,
        callback: Callable[["_SessionToolCaller"], Awaitable[McpToolCallResponse]],
    ) -> McpToolCallResponse:
        async with self._session(server) as session:
            return await callback(_SessionToolCaller(server, session, self))

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
        self._errlog = None

    async def __aenter__(self) -> ClientSession:
        self._errlog = self._open_errlog()
        self._stdio_context = stdio_client(self.params, errlog=self._errlog)
        read_stream, write_stream = await self._stdio_context.__aenter__()
        self._session_context = ClientSession(read_stream, write_stream)
        session = await self._session_context.__aenter__()
        await session.initialize()
        return session

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._session_context is not None:
            await self._session_context.__aexit__(exc_type, exc, tb)
        if self._stdio_context is not None:
            await self._stdio_context.__aexit__(exc_type, exc, tb)
        if self._errlog is not None and self._errlog is not os.sys.stderr:
            self._errlog.close()

    def _open_errlog(self):
        if os.getenv("MCP_ORCHESTRATOR_CHILD_LOGS", "").lower() in {"1", "true", "yes"}:
            return os.sys.stderr
        return open(os.devnull, "w", encoding="utf-8")


class _SessionToolCaller:
    def __init__(
        self,
        server: McpServerDefinition,
        session: ClientSession,
        runner: StdioMcpToolRunner,
    ) -> None:
        self.server = server
        self.session = session
        self.runner = runner

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> McpToolCallResponse:
        result = await self.session.call_tool(tool_name, arguments or {})
        return McpToolCallResponse(
            server_name=self.server.name,
            tool_name=tool_name,
            is_error=bool(getattr(result, "isError", False)),
            content=self.runner._content_text(result),
            structured_content=getattr(result, "structuredContent", None),
            raw_result=self.runner._dump(result),
        )
