from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class McpServerDefinition:
    name: str
    kind: str
    path: str
    command: str
    args: list[str]
    has_pyproject: bool
    has_requirements: bool
    readme_path: str | None = None
    package_name: str | None = None
    package_version: str | None = None


class LocalMcpServerCatalog:
    def __init__(self, mcps_dir: Path) -> None:
        self.mcps_dir = mcps_dir

    def list_servers(self) -> list[McpServerDefinition]:
        if not self.mcps_dir.exists():
            return []

        servers: list[McpServerDefinition] = []
        for server_dir in sorted(path for path in self.mcps_dir.iterdir() if path.is_dir()):
            server_file = server_dir / "server.py"
            if server_file.exists():
                servers.append(self._python_definition(server_dir, server_file))
                continue

            npm_definition = self._npm_definition(server_dir)
            if npm_definition:
                servers.append(npm_definition)
        return servers

    def status(self) -> dict[str, object]:
        servers = self.list_servers()
        return {
            "mcps_dir": str(self.mcps_dir),
            "server_count": len(servers),
            "servers": [server.__dict__ for server in servers],
        }

    def get(self, name: str) -> McpServerDefinition | None:
        normalized = self._normalize_name(name)
        for server in self.list_servers():
            if server.name == normalized:
                return server
        return None

    def _python_definition(self, server_dir: Path, server_file: Path) -> McpServerDefinition:
        readme = server_dir / "README.md"
        return McpServerDefinition(
            name=self._normalize_name(server_dir.name),
            kind="python",
            path=str(server_dir.resolve()),
            command=sys.executable,
            args=[str(server_file.resolve())],
            has_pyproject=(server_dir / "pyproject.toml").exists(),
            has_requirements=(server_dir / "requirements.txt").exists(),
            package_name=None,
            package_version=None,
            readme_path=str(readme) if readme.exists() else None,
        )

    def _npm_definition(self, server_dir: Path) -> McpServerDefinition | None:
        package_json_path = (
            server_dir
            / "node_modules"
            / "@microsoft"
            / "powerbi-modeling-mcp"
            / "package.json"
        )
        executable_path = self._powerbi_executable(server_dir)
        if not package_json_path.exists() or not executable_path.exists():
            return None

        package_data = json.loads(package_json_path.read_text(encoding="utf-8"))
        readme = server_dir / "README.md"
        return McpServerDefinition(
            name="power_bi",
            kind="npm",
            path=str(server_dir.resolve()),
            command=str(executable_path.resolve()),
            args=["--start"],
            has_pyproject=False,
            has_requirements=False,
            package_name=str(package_data.get("name") or ""),
            package_version=str(package_data.get("version") or ""),
            readme_path=str(readme) if readme.exists() else None,
        )

    def _powerbi_executable(self, server_dir: Path) -> Path:
        if sys.platform == "win32":
            return server_dir / "node_modules" / ".bin" / "powerbi-modeling-mcp.cmd"
        return server_dir / "node_modules" / ".bin" / "powerbi-modeling-mcp"

    def _normalize_name(self, folder_name: str) -> str:
        value = folder_name.lower()
        value = value.replace("-mcp-master", "")
        value = value.replace("_mcp_master", "")
        value = value.replace("-mcp", "")
        value = value.replace("_mcp", "")
        value = value.replace("-", "_")
        if value in {"postgressql", "postgresql"}:
            return "postgresql"
        if value in {"powerbi", "power_bi", "powerbi_modeling", "powerbi_modeling_mcp"}:
            return "power_bi"
        return value
