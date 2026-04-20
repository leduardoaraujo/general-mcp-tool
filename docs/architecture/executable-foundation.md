# MCP Orchestrator Executable Foundation

## Purpose

The MCP Orchestrator is a contextual middleware layer for specialist MCP servers.
It is not a raw router. Every specialist call is built from an enriched execution
payload that includes request understanding, local context, execution constraints,
and trace information.

## Phase 0 Flow

```text
UserRequest
  -> RequestUnderstanding
  -> RetrievedContext
  -> EnrichedRequest
  -> ExecutionPlan
  -> SpecialistExecutionRequest
  -> SpecialistExecutionResult
  -> NormalizedResponse
```

The FastAPI layer only validates input and delegates to the orchestration service.
Business rules, context retrieval, routing, execution, and normalization stay in
separate modules.

## Local Context

The default local context directory is:

```text
docs/context/
  business_rules/
  schemas/
  technical_docs/
  examples/
  playbooks/
```

The Phase 0 retriever is intentionally simple. It loads Markdown and text files,
splits them into chunks, scores chunks by token overlap, and returns typed
`RetrievedContextItem` objects. Embeddings can be added later behind the same
retriever interface.

## PostgreSQL MCP Integration

PostgreSQL is the first real specialist integration. The orchestrator discovers
the local server from:

```text
mcps/postgressql-mcp-master/server.py
```

The `PostgreSqlMcpClient` calls the server through the stdio MCP transport using
`StdioMcpToolRunner`. For `/orchestrate`, PostgreSQL requests use the
`run_guided_query` tool with:

```json
{
  "auto_execute": false,
  "limit": 100
}
```

This means Phase 0 produces a safe SQL preview. It does not execute data-row
queries unless a future explicit execution policy is added.

The `question` sent to PostgreSQL is derived from the enriched request. It
contains the original request, interpreted intent, task type, constraints, and
retrieved local context. The raw user request is not sent as the full specialist
payload.

## API Example

```json
{
  "message": "Use PostgreSQL to find the tables that can answer monthly sales revenue, then prepare a safe SQL preview.",
  "domain_hint": "postgresql",
  "tags": ["sales", "postgresql"],
  "metadata": {}
}
```

Response data is returned as `NormalizedResponse`. Specialist transport details,
including raw MCP tool results, are kept under `debug`.
