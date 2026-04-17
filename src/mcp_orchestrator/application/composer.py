from __future__ import annotations

from mcp_orchestrator.domain.models import (
    EnrichedRequest,
    OrchestrateRequest,
    RagContext,
    RequestInterpretation,
)


class DefaultContextComposer:
    def compose(
        self,
        correlation_id: str,
        request: OrchestrateRequest,
        interpretation: RequestInterpretation,
        rag_context: RagContext,
    ) -> EnrichedRequest:
        return EnrichedRequest(
            correlation_id=correlation_id,
            original_request=request.message,
            interpretation=interpretation,
            rag_context=rag_context,
            execution_instructions=[
                "Use the enriched interpretation and retrieved context.",
                "Do not treat the raw user request as sufficient context.",
                "Return structured data whenever possible.",
                "Preserve all sources used in the result.",
            ],
            constraints=[*interpretation.constraints],
            expected_response_format="NormalizedResponse",
        )
