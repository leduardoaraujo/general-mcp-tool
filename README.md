# General MCP Tool

This repository contains two Python packages:

- `powerbi_mcp_manager`: installs and updates the local `@microsoft/powerbi-modeling-mcp` package.
- `mcp_orchestrator`: a FastAPI-based contextual orchestrator for specialist MCP servers.

## MCP Orchestrator

The MCP Orchestrator is a contextual middleware layer. It does not send the raw
user request directly to specialist MCPs.

The executable Phase 0 flow is:

1. Receive a typed `UserRequest`.
2. Build a typed `RequestUnderstanding`.
3. Retrieve local context from `docs/context`.
4. Compose an `EnrichedRequest`.
5. Create an `ExecutionPlan`.
6. Execute a `SpecialistExecutionRequest` through a specialist MCP client.
7. Return a `NormalizedResponse`.

PostgreSQL is the first real specialist integration. Power BI, SQL Server, and
Excel remain registered as future extension points.

## Requirements

- Python 3.11+
- Node.js and npm on `PATH` for `powerbi_mcp_manager`
- PostgreSQL MCP environment variables when calling the real PostgreSQL MCP tools

## Installation

```powershell
python -m pip install -e .
```

Development dependencies:

```powershell
python -m pip install -e .[dev]
```

Install the checked-in PostgreSQL MCP server dependencies before calling it
through stdio:

```powershell
python -m pip install -r mcps/postgressql-mcp-master/requirements.txt
```

## Run The Orchestrator API

Development server:

```powershell
python -m uvicorn mcp_orchestrator.main:app --app-dir src --reload
```

Project entrypoint:

```powershell
mcp-orchestrator
```

Default URL:

```text
http://127.0.0.1:8000
```

## API Endpoints

- `GET /health`
- `POST /orchestrate`
- `GET /docs-index/status`
- `POST /docs-index/rebuild`
- `GET /mcp-servers/status`
- `GET /mcp-servers/{server_name}/tools`
- `POST /mcp-servers/{server_name}/tools/{tool_name}`

## `/orchestrate` Example

```json
{
  "message": "Use PostgreSQL to find the tables that can answer monthly sales revenue, then prepare a safe SQL preview.",
  "domain_hint": "postgresql",
  "tags": ["sales", "postgresql"],
  "metadata": {}
}
```

PowerShell:

```powershell
$body = @{
  message = "Use PostgreSQL to find tables for monthly sales revenue and prepare safe SQL."
  domain_hint = "postgresql"
  tags = @("sales", "postgresql")
  metadata = @{}
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/orchestrate" `
  -ContentType "application/json" `
  -Body $body
```

For PostgreSQL orchestration, Phase 0 calls `run_guided_query` with
`auto_execute=false`. The result is a safe SQL preview, not an automatic data-row
query execution.

## Local Context

The default context directory is:

```text
docs/context/
  business_rules/
  schemas/
  technical_docs/
  examples/
  playbooks/
```

Override it with:

```powershell
$env:MCP_ORCHESTRATOR_DOCS_DIR = "C:\path\to\context"
```

Rebuild the in-memory index without restarting:

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/docs-index/rebuild
```

## Specialist MCP Servers

Specialist MCP servers live under `mcps/`.

```text
mcps/
  powerbi-modeling-mcp/
  postgressql-mcp-master/
    server.py
```

The orchestrator does not import specialist server code directly. It discovers
local MCP servers and calls them through MCP transport adapters.

PostgreSQL MCP configuration is read by the PostgreSQL MCP server itself:

```env
POSTGRES_DSN=postgresql://user:password@localhost:5432/app_db
```

or:

```env
POSTGRES_DB_1_NAME=main
POSTGRES_DB_1_DSN=postgresql://user:password@localhost:5432/app_db
```

List discovered servers:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/mcp-servers/status
```

List PostgreSQL tools:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/mcp-servers/postgresql/tools
```

Call a PostgreSQL tool directly:

```powershell
$body = @{
  arguments = @{
    schema_name = "public"
  }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/mcp-servers/postgresql/tools/pg_list_tables" `
  -ContentType "application/json" `
  -Body $body
```

## Power BI MCP Manager

The Power BI manager installs the npm MCP package into a controlled local
directory.

Default installation directory:

```text
mcps/powerbi-modeling-mcp
```

Commands:

```powershell
powerbi-mcp-manager status
powerbi-mcp-manager install
powerbi-mcp-manager update
powerbi-mcp-manager check
powerbi-mcp-manager path
powerbi-mcp-manager config
```

Without installing entrypoints:

```powershell
python scripts/powerbi_mcp_manager.py status
python scripts/powerbi_mcp_manager.py install
python scripts/powerbi_mcp_manager.py update
python scripts/powerbi_mcp_manager.py check
python scripts/powerbi_mcp_manager.py path
python scripts/powerbi_mcp_manager.py config
```

## Tests

```powershell
python -m pytest
```

## Project Structure

```text
src/mcp_orchestrator/
  api/
  application/
  domain/
  infrastructure/
    context/
    mcp_clients/
    mcp_servers/
  normalization/
  observability/
```

See `docs/architecture/executable-foundation.md` for the implemented Phase 0
architecture.
