from __future__ import annotations

from mcp_orchestrator.domain.ports import McpClient

from .excel import ExcelMcpClient
from .postgresql import PostgreSqlMcpClient
from .powerbi import PowerBiMcpClient
from .sql_server import SqlServerMcpClient


class DefaultMcpClientRegistry:
    def __init__(self, clients: list[McpClient] | None = None) -> None:
        self._clients = clients or [
            PowerBiMcpClient(),
            PostgreSqlMcpClient(),
            SqlServerMcpClient(),
            ExcelMcpClient(),
        ]

    def all(self) -> list[McpClient]:
        return [*self._clients]

    def get(self, name: str) -> McpClient | None:
        for client in self._clients:
            if client.name == name:
                return client
        return None
