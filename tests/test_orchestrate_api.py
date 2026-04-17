from fastapi.testclient import TestClient

from mcp_orchestrator.config import Settings
from mcp_orchestrator.main import create_app


def test_health_endpoint() -> None:
    client = TestClient(create_app(Settings()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_orchestrate_endpoint_returns_normalized_response() -> None:
    client = TestClient(create_app(Settings()))

    response = client.post(
        "/orchestrate",
        json={"message": "Show Total Sales from the Power BI semantic model"},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["correlation_id"]
    assert body["summary"]
    assert body["mcp_trace"]
    assert body["raw_outputs"]


def test_docs_index_rebuild_updates_status() -> None:
    client = TestClient(create_app(Settings()))

    before = client.get("/docs-index/status").json()
    after = client.post("/docs-index/rebuild").json()

    assert before["document_count"] == after["document_count"]
    assert after["chunk_count"] >= 1
