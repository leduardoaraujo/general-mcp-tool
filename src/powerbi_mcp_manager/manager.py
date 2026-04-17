from __future__ import annotations

import json
import os
import platform
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_PACKAGE_NAME = "@microsoft/powerbi-modeling-mcp"
DEFAULT_TAG = "latest"
DEFAULT_MANAGED_DIR = "mcps/powerbi-modeling-mcp"


@dataclass(frozen=True)
class InstalledInfo:
    name: str
    version: str
    package_json_path: str
    executable_path: str


@dataclass(frozen=True)
class Status:
    package_name: str
    tracked_tag: str
    latest_version: str
    dist_tags: dict[str, str]
    installed_version: str | None
    installed: InstalledInfo | None
    managed_dir: str
    npm_cache_dir: str
    state: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["installed"] = asdict(self.installed) if self.installed else None
        return data


@dataclass(frozen=True)
class UpdateResult:
    updated: bool
    previous_version: str | None
    installed: InstalledInfo


class PowerBiMcpManager:
    """Manage a local install of the Power BI Modeling MCP npm package."""

    def __init__(
        self,
        *,
        project_dir: str | os.PathLike[str] | None = None,
        package_name: str | None = None,
        tag: str | None = None,
        managed_dir: str | os.PathLike[str] | None = None,
        npm_cache_dir: str | os.PathLike[str] | None = None,
        npm_command: str | None = None,
    ) -> None:
        self.project_dir = Path(project_dir or Path.cwd()).resolve()
        self.package_name = (
            package_name or os.getenv("POWERBI_MCP_PACKAGE") or DEFAULT_PACKAGE_NAME
        )
        self.tag = tag or os.getenv("POWERBI_MCP_TAG") or DEFAULT_TAG
        self.managed_dir = self._resolve_dir(
            managed_dir
            or os.getenv("POWERBI_MCP_DIR")
            or DEFAULT_MANAGED_DIR
        )
        self.npm_cache_dir = self._resolve_dir(
            npm_cache_dir or os.getenv("POWERBI_MCP_NPM_CACHE") or ".npm-cache"
        )
        self.npm_command = npm_command or (
            "npm.cmd" if platform.system() == "Windows" else "npm"
        )

    def _resolve_dir(self, value: str | os.PathLike[str]) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return (self.project_dir / path).resolve()

    def _run_npm(
        self,
        args: list[str],
        *,
        capture: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        self.npm_cache_dir.mkdir(parents=True, exist_ok=True)
        command = [self.npm_command, *args, "--cache", str(self.npm_cache_dir)]
        result = subprocess.run(
            command,
            cwd=self.project_dir,
            text=True,
            capture_output=capture,
            check=False,
        )
        if result.returncode != 0:
            details = "\n".join(
                part.strip()
                for part in [result.stderr or "", result.stdout or ""]
                if part.strip()
            )
            raise RuntimeError(f"npm failed: {' '.join(command)}\n{details}".strip())
        return result

    def _npm_json(self, args: list[str]) -> Any:
        result = self._run_npm([*args, "--json"])
        output = (result.stdout or "").strip()
        if not output:
            return None
        return json.loads(output)

    def remote_version(self) -> str:
        version = self._npm_json(["view", f"{self.package_name}@{self.tag}", "version"])
        if isinstance(version, list):
            return str(version[-1])
        return str(version)

    def dist_tags(self) -> dict[str, str]:
        tags = self._npm_json(["view", self.package_name, "dist-tags"]) or {}
        return {str(key): str(value) for key, value in dict(tags).items()}

    def package_json_path(self) -> Path:
        package_path = Path(*self.package_name.split("/"))
        return self.managed_dir / "node_modules" / package_path / "package.json"

    def executable_path(self) -> str:
        installed = self.installed_info()
        if not installed:
            raise RuntimeError("Package is not installed. Run install() first.")
        return installed.executable_path

    def _expected_executable_path(self) -> Path:
        bin_name = (
            "powerbi-modeling-mcp.cmd"
            if platform.system() == "Windows"
            else "powerbi-modeling-mcp"
        )
        return self.managed_dir / "node_modules" / ".bin" / bin_name

    def installed_info(self) -> InstalledInfo | None:
        package_json_path = self.package_json_path()
        if not package_json_path.exists():
            return None

        package_data = json.loads(package_json_path.read_text(encoding="utf-8"))
        return InstalledInfo(
            name=str(package_data["name"]),
            version=str(package_data["version"]),
            package_json_path=str(package_json_path),
            executable_path=str(self._expected_executable_path()),
        )

    def status(self) -> Status:
        latest_version = self.remote_version()
        installed = self.installed_info()
        installed_version = installed.version if installed else None

        if installed_version is None:
            state = "not-installed"
        elif installed_version == latest_version:
            state = "up-to-date"
        else:
            state = "update-available"

        return Status(
            package_name=self.package_name,
            tracked_tag=self.tag,
            latest_version=latest_version,
            dist_tags=self.dist_tags(),
            installed_version=installed_version,
            installed=installed,
            managed_dir=str(self.managed_dir),
            npm_cache_dir=str(self.npm_cache_dir),
            state=state,
        )

    def ensure_managed_project(self) -> None:
        self.managed_dir.mkdir(parents=True, exist_ok=True)
        package_json_path = self.managed_dir / "package.json"
        if package_json_path.exists():
            return

        package_json_path.write_text(
            json.dumps(
                {
                    "name": "managed-powerbi-modeling-mcp",
                    "version": "0.0.0",
                    "private": True,
                    "description": (
                        "Generated local install area for "
                        "@microsoft/powerbi-modeling-mcp."
                    ),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def install(self, version: str | None = None) -> InstalledInfo:
        self.ensure_managed_project()
        target = version or self.tag
        self._run_npm(
            [
                "install",
                f"{self.package_name}@{target}",
                "--save-exact",
                "--no-audit",
                "--no-fund",
                "--prefix",
                str(self.managed_dir),
            ],
            capture=True,
        )

        installed = self.installed_info()
        if not installed:
            raise RuntimeError("Package install finished, but the package was not found.")
        return installed

    def update(self) -> UpdateResult:
        current_status = self.status()
        if current_status.state == "up-to-date" and current_status.installed:
            return UpdateResult(
                updated=False,
                previous_version=current_status.installed_version,
                installed=current_status.installed,
            )

        installed = self.install(current_status.latest_version)
        return UpdateResult(
            updated=True,
            previous_version=current_status.installed_version,
            installed=installed,
        )

    def mcp_config(self, args: list[str] | None = None) -> dict[str, Any]:
        installed = self.installed_info()
        if not installed:
            raise RuntimeError("Package is not installed. Run install() first.")

        return {
            "servers": {
                "powerbi-modeling-mcp": {
                    "type": "stdio",
                    "command": installed.executable_path,
                    "args": args or ["--start"],
                    "env": {},
                }
            }
        }
