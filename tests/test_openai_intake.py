import json

import httpx

from mcp_orchestrator.application import OpenAIRequestUnderstandingService
from mcp_orchestrator.domain.enums import Domain, McpTarget, RequestedAction, TaskType
from mcp_orchestrator.domain.models import UserRequest


def test_openai_understanding_uses_structured_response() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "output_text": json.dumps(
                    {
                        "original_request": "List Power BI semantic model measures.",
                        "intent": "Inspect semantic model measures.",
                        "domain": "power_bi",
                        "task_type": "semantic_model_inspection",
                        "requested_action": "inspect_model",
                        "target_preference": "power_bi",
                        "relevant_sources": ["business_rules", "schemas"],
                        "candidate_mcps": ["power_bi"],
                        "constraints": [],
                        "ambiguities": [],
                        "confidence": 0.91,
                        "risk_level": "low",
                        "reasoning_summary": "Power BI metadata inspection.",
                    }
                )
            },
        )

    service = OpenAIRequestUnderstandingService(
        api_key="test-key",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )

    understanding = service.understand(
        UserRequest(message="List Power BI semantic model measures.")
    )

    assert requests[0]["model"] == "test-model"
    assert requests[0]["text"]["format"]["type"] == "json_schema"  # type: ignore[index]
    assert understanding.domain == Domain.POWER_BI
    assert understanding.task_type == TaskType.SEMANTIC_MODEL_INSPECTION
    assert understanding.requested_action == RequestedAction.INSPECT_MODEL
    assert understanding.candidate_mcps == [McpTarget.POWER_BI]


def test_openai_understanding_falls_back_when_api_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "failed"})

    service = OpenAIRequestUnderstandingService(
        api_key="test-key",
        model="test-model",
        transport=httpx.MockTransport(handler),
    )

    understanding = service.understand(
        UserRequest(message="Use PostgreSQL to prepare safe SQL.")
    )

    assert understanding.domain == Domain.POSTGRESQL
    assert understanding.candidate_mcps == [McpTarget.POSTGRESQL]
