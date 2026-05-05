import json

import httpx
import pytest

from mcp_orchestrator.mcp_proxy import (
    POWERBI_TOOL_NAMES,
    OrchestratorProxyClient,
    OrchestratorProxySettings,
    create_mcp_server,
)


def build_client(transport: httpx.MockTransport) -> OrchestratorProxyClient:
    return OrchestratorProxyClient(
        OrchestratorProxySettings(api_url="http://orchestrator.test", timeout_seconds=5),
        transport=transport,
    )


@pytest.mark.asyncio
async def test_ask_orchestrator_posts_contextual_request_without_debug_by_default() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "correlation_id": "request-1",
                "status": "success",
                "summary": "ok",
                "structured_data": {"answer": 42},
                "sources_used": ["docs/context/example.md"],
                "warnings": [],
                "errors": [],
                "next_actions": ["review"],
                "confirmation_id": "confirmation-1",
                "specialist_results": [{"mcp_name": "power_bi"}],
                "mcp_trace": ["routed to power_bi"],
                "timings": {"total": 1.2},
                "debug": {"orchestration_trace": {"large": True}},
            },
        )

    result = await build_client(httpx.MockTransport(handler)).ask(
        message="qual a medida de custo unitario por prato?",
        domain_hint="power_bi",
        tags=["powerbi"],
    )

    assert requests == [
        {
            "message": "qual a medida de custo unitario por prato?",
            "domain_hint": "power_bi",
            "tags": ["powerbi"],
            "metadata": {},
        }
    ]
    assert result["ok"] is True
    assert result["summary"] == "ok"
    assert result["structured_data"] == {"answer": 42}
    assert result["confirmation_id"] == "confirmation-1"
    assert "debug" not in result


@pytest.mark.asyncio
async def test_ask_orchestrator_can_allow_execution_and_include_debug() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "correlation_id": "request-2",
                "status": "success",
                "summary": "ok",
                "debug": {"orchestration_trace": {"request_id": "request-2"}},
            },
        )

    result = await build_client(httpx.MockTransport(handler)).ask(
        message="execute uma consulta somente leitura",
        allow_execution=True,
        confirmation_id="confirmation-1",
        include_debug=True,
    )

    assert requests[0]["metadata"] == {
        "allow_execution": True,
        "confirmation_id": "confirmation-1",
    }
    assert result["debug"] == {"orchestration_trace": {"request_id": "request-2"}}


@pytest.mark.asyncio
async def test_execute_confirmation_posts_to_confirmation_endpoint() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(
            200,
            json={
                "confirmation_id": "confirmation-1",
                "status": "executed",
                "response": {
                    "correlation_id": "request-3",
                    "status": "success",
                    "summary": "ok",
                    "confirmation_id": "confirmation-1",
                },
            },
        )

    result = await build_client(httpx.MockTransport(handler)).execute_confirmation(
        "confirmation-1"
    )

    assert requests == ["/confirmations/confirmation-1/execute"]
    assert result["ok"] is True
    assert result["confirmation_id"] == "confirmation-1"
    assert result["confirmation_status"] == "executed"


@pytest.mark.asyncio
async def test_orchestrator_health_returns_api_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/health"
        return httpx.Response(200, json={"status": "ok", "service": "mcp_orchestrator"})

    result = await build_client(httpx.MockTransport(handler)).health()

    assert result == {
        "ok": True,
        "api_url": "http://orchestrator.test",
        "status": "ok",
        "service": "mcp_orchestrator",
        "data": {"status": "ok", "service": "mcp_orchestrator"},
    }


@pytest.mark.asyncio
async def test_proxy_reports_api_connection_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    result = await build_client(httpx.MockTransport(handler)).health()

    assert result["ok"] is False
    assert result["api_url"] == "http://orchestrator.test"
    assert result["error"] == "Orchestrator API unavailable at http://orchestrator.test"
    assert "connection refused" in result["detail"]


@pytest.mark.asyncio
async def test_proxy_preserves_http_error_status_and_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"detail": "specialist MCP failed"})

    result = await build_client(httpx.MockTransport(handler)).ask(message="teste")

    assert result["ok"] is False
    assert result["status_code"] == 502
    assert result["error"] == "specialist MCP failed"
    assert result["detail"] == {"detail": "specialist MCP failed"}


@pytest.mark.asyncio
async def test_call_powerbi_tool_posts_to_direct_power_bi_endpoint() -> None:
    requests: list[tuple[str, dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.url.path, json.loads(request.content.decode("utf-8"))))
        return httpx.Response(
            200,
            json={
                "server_name": "power_bi",
                "tool_name": "measure_operations",
                "is_error": False,
                "content": ["ok"],
                "structured_content": {"data": [{"name": "Total Custo"}]},
                "raw_result": {"transport": "stdio"},
            },
        )

    result = await build_client(httpx.MockTransport(handler)).call_powerbi_tool(
        "measure_operations",
        {"operation": "List", "filter": {"maxResults": 10}},
    )

    assert requests == [
        (
            "/mcp-servers/power_bi/tools/measure_operations",
            {
                "arguments": {
                    "request": {"operation": "List", "filter": {"maxResults": 10}}
                }
            },
        )
    ]
    assert result["ok"] is True
    assert result["server_name"] == "power_bi"
    assert result["tool_name"] == "measure_operations"
    assert result["structured_content"] == {"data": [{"name": "Total Custo"}]}


@pytest.mark.asyncio
async def test_call_powerbi_tool_reports_tool_level_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "server_name": "power_bi",
                "tool_name": "connection_operations",
                "is_error": True,
                "content": ["failed"],
                "structured_content": None,
                "raw_result": {"isError": True},
            },
        )

    result = await build_client(httpx.MockTransport(handler)).call_powerbi_tool(
        "connection_operations",
        {"operation": "ConnectFabric"},
    )

    assert result["ok"] is False
    assert result["is_error"] is True
    assert result["content"] == ["failed"]


@pytest.mark.asyncio
async def test_mcp_server_registers_one_proxy_tool_for_each_power_bi_tool() -> None:
    tool_names = {tool.name for tool in await create_mcp_server().list_tools()}

    assert "ask_orchestrator" in tool_names
    assert "execute_confirmation" in tool_names
    assert "orchestrator_health" in tool_names
    for tool_name in POWERBI_TOOL_NAMES:
        assert f"powerbi_{tool_name}" in tool_names
