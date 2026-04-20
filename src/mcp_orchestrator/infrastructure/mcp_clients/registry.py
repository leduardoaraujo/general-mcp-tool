from __future__ import annotations

from pathlib import Path

from mcp_orchestrator.domain.enums import McpTarget
from mcp_orchestrator.domain.ports import BaseMCPClient
from mcp_orchestrator.infrastructure.mcp_servers import LocalMcpServerCatalog, StdioMcpToolRunner

from .excel import ExcelMcpClient
from .postgresql import PostgreSqlMcpClient
from .powerbi import PowerBiMcpClient
from .sql_server import SqlServerMcpClient


class DefaultMcpClientRegistry:
    def __init__(
        self,
        *,
        clients: list[BaseMCPClient] | None = None,
        server_catalog: LocalMcpServerCatalog | None = None,
        tool_runner: StdioMcpToolRunner | None = None,
    ) -> None:
        if clients is not None:
            self._clients = clients
            return

        server_catalog = server_catalog or LocalMcpServerCatalog(Path.cwd() / "mcps")
        tool_runner = tool_runner or StdioMcpToolRunner()

        self._clients: list[BaseMCPClient] = [
            PostgreSqlMcpClient(server_catalog=server_catalog, tool_runner=tool_runner),
            PowerBiMcpClient(),
            SqlServerMcpClient(),
            ExcelMcpClient(),
        ]

    def all(self) -> list[BaseMCPClient]:
        return [*self._clients]

    def get(self, target: McpTarget | str) -> BaseMCPClient | None:
        normalized = self._target_value(target)
        for client in self._clients:
            if client.target.value == normalized or client.name == normalized:
                return client
        return None

    def _target_value(self, target: McpTarget | str) -> str:
        if isinstance(target, McpTarget):
            return target.value
        return target
