from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mcp_orchestrator.config import Settings
from mcp_orchestrator.infrastructure.mcp_servers import LocalMcpServerCatalog
from mcp_orchestrator.main import create_app


def create_fake_power_bi_mcp(root: Path) -> None:
    package_dir = root / "powerbi-modeling-mcp"
    package_json = (
        package_dir
        / "node_modules"
        / "@microsoft"
        / "powerbi-modeling-mcp"
        / "package.json"
    )
    executable = (
        package_dir
        / "node_modules"
        / "@microsoft"
        / "powerbi-modeling-mcp-win32-x64"
        / "dist"
        / "powerbi-modeling-mcp.exe"
    )
    package_json.parent.mkdir(parents=True)
    executable.parent.mkdir(parents=True)
    package_json.write_text(
        '{"name": "@microsoft/powerbi-modeling-mcp", "version": "0.5.0-beta.5"}',
        encoding="utf-8",
    )
    executable.write_text("fake executable", encoding="utf-8")


def test_catalog_discovers_local_postgresql_server() -> None:
    catalog = LocalMcpServerCatalog(Path("mcps"))

    status = catalog.status()

    assert status["server_count"] >= 1
    names = {server["name"] for server in status["servers"]}
    assert "postgresql" in names


def test_catalog_marks_power_bi_as_npm_server(tmp_path: Path) -> None:
    create_fake_power_bi_mcp(tmp_path)
    catalog = LocalMcpServerCatalog(tmp_path)

    servers = catalog.status()["servers"]
    power_bi = next(server for server in servers if server["name"] == "power_bi")

    assert power_bi["kind"] == "npm"
    assert power_bi["package_name"] == "@microsoft/powerbi-modeling-mcp"
    assert "powerbi-modeling-mcp" in power_bi["command"]


def test_catalog_accepts_powerbi_alias(tmp_path: Path) -> None:
    create_fake_power_bi_mcp(tmp_path)
    catalog = LocalMcpServerCatalog(tmp_path)

    server = catalog.get("powerbi")

    assert server is not None
    assert server.name == "power_bi"


@pytest.mark.parametrize(
    ("folder_name", "alias"),
    [
        ("sql-server-mcp", "sql-server"),
        ("sqlserver-mcp", "sqlserver"),
        ("mssql-mcp", "mssql"),
    ],
)
def test_catalog_accepts_sql_server_aliases(tmp_path: Path, folder_name: str, alias: str) -> None:
    server_dir = tmp_path / folder_name
    server_dir.mkdir()
    (server_dir / "server.py").write_text("print('sql server mcp')", encoding="utf-8")
    catalog = LocalMcpServerCatalog(tmp_path)

    server = catalog.get(alias)

    assert server is not None
    assert server.name == "sql_server"


def test_api_exposes_mcp_servers_status() -> None:
    client = TestClient(create_app(Settings()))

    response = client.get("/mcp-servers/status")

    assert response.status_code == 200
    assert response.json()["server_count"] >= 1
