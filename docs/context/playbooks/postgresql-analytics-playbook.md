# PostgreSQL Analytics Playbook

Tags: postgresql, analytics, sql, sales

For PostgreSQL analytical requests, enrich the user request with local business rules and schema context before calling the specialist MCP.

Prefer a safe SQL preview first. The user or a future explicit execution flag can approve read-only execution later.

Keep generated SQL focused on the requested analysis and include conservative limits when previewing row-level output.
