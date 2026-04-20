from __future__ import annotations

from mcp_orchestrator.domain.models import (
    EnrichedRequest,
    RequestUnderstanding,
    RetrievedContext,
    UserRequest,
)


class DefaultContextComposer:
    def compose(
        self,
        correlation_id: str,
        request: UserRequest,
        understanding: RequestUnderstanding,
        retrieved_context: RetrievedContext,
    ) -> EnrichedRequest:
        return EnrichedRequest(
            correlation_id=correlation_id,
            original_request=request.message,
            understanding=understanding,
            retrieved_context=retrieved_context,
            execution_instructions=[
                "Use the enriched understanding and retrieved context.",
                "Do not treat the raw user request as sufficient context.",
                "Return structured data whenever possible.",
                "Preserve all sources used in the result.",
            ],
            constraints=[*understanding.constraints],
            expected_response_format="NormalizedResponse",
        )
