# postgres-mcp

PostgreSQL MCP server focused on read-only queries and schema inspection, with support for up to 3 named database connections.

## Tools

- `pg_execute_query`: validates and executes a single read-only SQL query.
- `pg_list_tables`: lists user tables with size and row estimates.
- `pg_describe_table`: describes columns, foreign keys, and indexes for a table.

All tools accept an optional `database` parameter. When omitted, the server uses the default configured database.

## Configuration

Copy [`.env.example`](.env.example) to `.env` and choose one mode.

### Legacy single-database mode

```env
POSTGRES_DSN=postgresql://user:password@localhost:5432/app_db
```

### Multi-database mode

Slot 1 is required and becomes the default alias. Slots 2 and 3 are optional.

```env
POSTGRES_DB_1_NAME=main
POSTGRES_DB_1_DSN=postgresql://user:password@localhost:5432/app_db
POSTGRES_DB_2_NAME=analytics
POSTGRES_DB_2_DSN=postgresql://user:password@localhost:5432/analytics_db
POSTGRES_DB_3_NAME=billing
POSTGRES_DB_3_DSN=postgresql://user:password@localhost:5432/billing_db
```

### Optional tuning

```env
POOL_MIN_SIZE=1
POOL_MAX_SIZE=3
POOL_COMMAND_TIMEOUT=30
POOL_CONNECT_TIMEOUT=10
QUERY_STATEMENT_TIMEOUT_MS=10000
QUERY_LOCK_TIMEOUT_MS=1000
QUERY_IDLE_IN_TRANSACTION_TIMEOUT_MS=15000
```

## Installation

```bash
python -m pip install -r requirements.txt
python -m pip install -e ".[dev]"
```

## Running

```bash
python server.py
```

## Claude Desktop

```json
{
  "mcpServers": {
    "postgres": {
      "command": "python",
      "args": ["C:/path/to/axis-postgres-mcp/server.py"],
      "env": {
        "POSTGRES_DB_1_NAME": "main",
        "POSTGRES_DB_1_DSN": "postgresql://user:password@host:5432/app_db",
        "POSTGRES_DB_2_NAME": "analytics",
        "POSTGRES_DB_2_DSN": "postgresql://user:password@host:5432/analytics_db"
      }
    }
  }
}
```

## Example tool inputs

```json
{
  "sql": "SELECT id, email FROM users ORDER BY id DESC",
  "limit": 50,
  "format": "markdown",
  "database": "main"
}
```

```json
{
  "schema_name": "public",
  "database": "analytics"
}
```

## Security model

- The server only accepts a single validated read-only SQL statement for `pg_execute_query`.
- Every tool runs inside a read-only transaction with local statement, lock, and idle-in-transaction timeouts.
- The server sanitizes database errors before returning them to the MCP client.
- Logs never include the full DSN or password.
- You should still connect with a PostgreSQL role that only has `SELECT` and metadata access.

Recommended role setup:

```sql
CREATE ROLE mcp_reader WITH LOGIN PASSWORD 'secret';
GRANT CONNECT ON DATABASE app_db TO mcp_reader;
GRANT USAGE ON SCHEMA public TO mcp_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO mcp_reader;
```

## Testing

Run the unit suite:

```bash
python -m pytest
```

Run integration tests only when you have real database credentials available:

```bash
python -m pytest -m integration
```
