# PostgreSQL MCP Technical Notes

Tags: postgresql, mcp, sql, preview

The PostgreSQL MCP is the first real specialist integration for the orchestrator.

Use `run_guided_query` when the request is a natural-language analytical or database question.

For Phase 0 orchestration, call `run_guided_query` with `auto_execute=false` so the MCP returns a safe SQL preview instead of executing against database rows.

Use `pg_list_tables` and `pg_describe_table` for direct schema inspection workflows.
