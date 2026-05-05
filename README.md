# Orquestra-MCP

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
5. Make an `ExecutionPolicyDecision`.
6. Create an `ExecutionPlan`.
7. Execute a `SpecialistExecutionRequest` through a specialist MCP client.
8. Return a `NormalizedResponse`.

PostgreSQL and SQL Server are real relational specialist client adapters. Power
BI is a real semantic/modeling specialist client adapter. Excel remains
registered as a future extension point.

The PostgreSQL MCP server is checked into this repository. The Power BI Modeling
MCP package is managed under `mcps/powerbi-modeling-mcp`. SQL Server expects a
local MCP server folder such as `mcps/sql-server-mcp`, `mcps/sqlserver-mcp`, or
`mcps/mssql-mcp` before live execution can work.

## Execution Governance

The orchestrator makes an explicit policy decision before any specialist MCP
call. The policy captures:

- `preview_only`
- `read_only`
- `write`
- `side_effects`
- `requires_confirmation`
- `allow_execution`
- `blocked_reason`
- `safety_level`

Phase 3 is preview-first for relational and semantic backends. PostgreSQL and
SQL Server orchestration call `run_guided_query` with `auto_execute=false`
unless request metadata explicitly allows read-only execution. Power BI
orchestration uses safe semantic-model inspection and DAX preview workflows by
default.

```json
{
  "metadata": {
    "allow_execution": true
  }
}
```

Write, refresh, model mutation, or side-effecting requests are blocked before a
specialist MCP is called. The policy decision is included in
`debug.orchestration_trace`.

Read-only execution now requires an explicit confirmation flow. A safe preview
for a read-only request returns `confirmation_id`; execution only proceeds when
the caller sends both `metadata.allow_execution=true` and that pending
`confirmation_id`, or calls the confirmation execution endpoint.

Audit events and confirmations are persisted to SQLite. The default database is:

```text
data/orchestrator.sqlite3
```

Override it with:

```powershell
$env:MCP_ORCHESTRATOR_AUDIT_DB = "C:\path\to\orchestrator.sqlite3"
```

## Requirements

- Python 3.11+
- Node.js and npm on `PATH` for `powerbi_mcp_manager`
- PostgreSQL MCP environment variables when calling the real PostgreSQL MCP tools
- A local SQL Server MCP server folder when calling SQL Server tools live
- Power BI Desktop, Fabric, or PBIP setup when calling the real Power BI Modeling MCP tools live

Optional OpenAI request understanding:

```powershell
$env:MCP_ORCHESTRATOR_INTELLIGENCE_MODE = "openai"
$env:OPENAI_API_KEY = "..."
$env:OPENAI_MODEL = "gpt-5-mini"
```

If OpenAI is not configured or a request fails, the orchestrator falls back to
the local heuristic interpreter.

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

The local chat UI is served by the same FastAPI app:

```text
http://127.0.0.1:8000/
```

## Run The MCP Client Proxy

The MCP proxy is a lightweight stdio server for MCP clients. It does not start
or embed the orchestrator; start the FastAPI service first:

```powershell
python -m uvicorn mcp_orchestrator.main:app --app-dir src --reload
```

Then configure the MCP client to run the proxy:

```powershell
mcp-orchestrator-proxy
```

The proxy calls the orchestrator API at `http://127.0.0.1:8000` by default.
Override it when needed:

```powershell
$env:MCP_ORCHESTRATOR_API_URL = "http://127.0.0.1:8000"
$env:MCP_ORCHESTRATOR_TIMEOUT_SECONDS = "60"
mcp-orchestrator-proxy
```

Example MCP client stdio configuration:

```json
{
  "mcpServers": {
    "orquestra-mcp": {
      "command": "mcp-orchestrator-proxy",
      "args": [],
      "env": {
        "MCP_ORCHESTRATOR_API_URL": "http://127.0.0.1:8000"
      }
    }
  }
}
```

If the package is not installed with entrypoints, use Python directly:

```json
{
  "mcpServers": {
    "orquestra-mcp": {
      "command": "python",
      "args": ["-m", "mcp_orchestrator.mcp_proxy"],
      "env": {
        "PYTHONPATH": "src",
        "MCP_ORCHESTRATOR_API_URL": "http://127.0.0.1:8000"
      }
    }
  }
}
```

Proxy tools:

- `ask_orchestrator`: sends a contextual request to `POST /orchestrate`.
- `orchestrator_health`: checks `GET /health` and reports whether the API is reachable.
- `powerbi_*`: one proxy tool per Microsoft Power BI Modeling MCP tool, routed
  through `POST /mcp-servers/power_bi/tools/{tool_name}`. Each tool receives the
  inner Power BI `request` object.

Examples:

```json
{
  "tool": "powerbi_connection_operations",
  "arguments": {
    "request": {
      "operation": "ConnectFabric",
      "workspaceName": "Finance Workspace",
      "semanticModelName": "Planejamento",
      "tenantName": "myorg",
      "clearCredential": false
    }
  }
}
```

```json
{
  "tool": "powerbi_measure_operations",
  "arguments": {
    "request": {
      "operation": "List",
      "filter": {
        "maxResults": 200
      }
    }
  }
}
```

Available Power BI proxy tools:

```text
powerbi_database_operations
powerbi_trace_operations
powerbi_named_expression_operations
powerbi_measure_operations
powerbi_object_translation_operations
powerbi_dax_query_operations
powerbi_perspective_operations
powerbi_column_operations
powerbi_user_hierarchy_operations
powerbi_calculation_group_operations
powerbi_security_role_operations
powerbi_table_operations
powerbi_calendar_operations
powerbi_relationship_operations
powerbi_model_operations
powerbi_culture_operations
powerbi_function_operations
powerbi_query_group_operations
powerbi_transaction_operations
powerbi_connection_operations
powerbi_partition_operations
```

## API Endpoints

- `GET /health`
- `GET /`
- `POST /chat`
- `POST /chat/confirmations/{confirmation_id}/execute`
- `POST /orchestrate`
- `GET /docs-index/status`
- `POST /docs-index/rebuild`
- `GET /business-rules/status`
- `GET /audit/{correlation_id}`
- `POST /confirmations/{confirmation_id}/execute`
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

For relational orchestration, Phase 3 calls `run_guided_query` with
`auto_execute=false`. The result is a safe SQL preview, not an automatic data-row
query execution.

For Power BI orchestration, Phase 3 calls a guided semantic modeling request in
preview/safe mode. Metadata exploration, table listing, measure listing, and DAX
preview are treated as safe. Refresh and model mutation are blocked by default.

To explicitly allow read-only execution in Phase 1:

```json
{
  "message": "Read rows from PostgreSQL sales_orders.",
  "domain_hint": "postgresql",
  "tags": ["sales", "postgresql"],
  "metadata": {
    "allow_execution": true
  }
}
```

This opt-in is ignored for write or side-effecting requests, which remain
blocked until a confirmation workflow exists.

## Traceability

`NormalizedResponse.debug.orchestration_trace` contains a typed trace with:

- request id
- stage timestamps and durations
- selected target MCPs
- retrieved context sources
- policy decision
- warnings and fallback information
- debug notes

Low-level MCP transport details stay inside each specialist result `debug`
object and are not promoted into the main response fields.

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

Business rules are versioned Markdown files under:

```text
docs/context/business_rules/<domain>/<rule_id>.md
```

Each rule must include these headers:

```text
Rule ID
Domain
Tags
Applies To
Business Definition
Data Sources
SQL/DAX Guidance
Validation Notes
Owner
Last Reviewed
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
  sql-server-mcp/
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

SQL Server MCP setup is expected to mirror the relational MCP contract:

- schema discovery
- table listing
- safe query preview through `run_guided_query`
- optional read-only execution when governance allows it
- no write or side-effecting execution by default

The SQL Server client adapter is implemented, but this repository does not yet
include a SQL Server MCP server. Add a local server folder under `mcps/` using an
alias such as `sql-server-mcp`, `sqlserver-mcp`, or `mssql-mcp`.

Power BI MCP setup is managed by `powerbi_mcp_manager`. The local package is
expected at:

```text
mcps/powerbi-modeling-mcp
```

The Power BI Modeling MCP requires a connection to a semantic model through
Power BI Desktop, Fabric, or PBIP files before live model operations can work.
The orchestrator treats metadata/model exploration and DAX previews as safe
operations. Refresh and model write operations remain blocked by execution
policy unless a future confirmation workflow is added.

List discovered servers:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/mcp-servers/status
```

List PostgreSQL tools:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/mcp-servers/postgresql/tools
```

List SQL Server tools after adding a local SQL Server MCP server:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/mcp-servers/sql_server/tools
```

List Power BI tools:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/mcp-servers/power_bi/tools
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

See `docs/architecture/executable-foundation.md` and
`docs/architecture/phase-2-multi-backend-orchestration.md` and
`docs/architecture/phase-3-power-bi-specialist.md` for the implemented
architecture.
