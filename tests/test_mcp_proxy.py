import json

import httpx
import pytest

from mcp_orchestrator.mcp_proxy import OrchestratorProxyClient, OrchestratorProxySettings


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
        include_debug=True,
    )

    assert requests[0]["metadata"] == {"allow_execution": True}
    assert result["debug"] == {"orchestration_trace": {"request_id": "request-2"}}


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
