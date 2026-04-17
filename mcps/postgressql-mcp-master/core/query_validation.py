import re
from dataclasses import dataclass

from sqlglot import exp, parse
from sqlglot.errors import ParseError

from core.errors import MCPToolError

LOCKING_CLAUSE_RE = re.compile(
    r"\bFOR\s+(UPDATE|SHARE|NO\s+KEY\s+UPDATE|KEY\s+SHARE)\b",
    re.IGNORECASE,
)
ADVISORY_LOCK_RE = re.compile(
    r"\bpg_(try_)?advisory(_xact)?_lock(_shared)?\b",
    re.IGNORECASE,
)


def _expression_types(*names: str) -> tuple[type[exp.Expression], ...]:
    return tuple(getattr(exp, name) for name in names if hasattr(exp, name))


DISALLOWED_EXPRESSION_TYPES = _expression_types(
    "Analyze",
    "Alter",
    "Attach",
    "Call",
    "Command",
    "Commit",
    "Copy",
    "Create",
    "Delete",
    "Detach",
    "Drop",
    "Explain",
    "Grant",
    "Insert",
    "Lock",
    "Merge",
    "Refresh",
    "Revoke",
    "Rollback",
    "Set",
    "Show",
    "Transaction",
    "TruncateTable",
    "Update",
    "Use",
    "Vacuum",
)

ALLOWED_STATEMENT_TYPES = _expression_types("Select", "Union", "Intersect", "Except")


@dataclass(frozen=True)
class NormalizedQuery:
    sql: str
    limit_applied: int


def _strip_optional_trailing_semicolon(sql: str) -> str:
    stripped = sql.strip()
    if stripped.endswith(";"):
        return stripped[:-1].rstrip()
    return stripped


def _extract_existing_limit(statement: exp.Expression) -> int | None:
    limit_expression = statement.args.get("limit")
    if limit_expression is None:
        return None

    expression = getattr(limit_expression, "expression", None)
    if expression is None and hasattr(limit_expression, "args"):
        expression = limit_expression.args.get("expression")

    if expression is None:
        return None

    raw_value = getattr(expression, "this", None)
    if raw_value is None and hasattr(expression, "sql"):
        raw_value = expression.sql(dialect="postgres")

    try:
        return int(str(raw_value))
    except (TypeError, ValueError):
        return None


def _contains_disallowed_expressions(statement: exp.Expression) -> bool:
    return any(isinstance(node, DISALLOWED_EXPRESSION_TYPES) for node in statement.walk())


def normalize_readonly_query(sql: str, limit: int) -> NormalizedQuery:
    normalized_input = _strip_optional_trailing_semicolon(sql)
    if not normalized_input:
        raise MCPToolError(
            code="invalid_query",
            message="SQL query cannot be empty.",
            retryable=False,
        )

    try:
        statements = [statement for statement in parse(normalized_input, read="postgres") if statement]
    except ParseError as exc:
        raise MCPToolError(
            code="invalid_query",
            message="Only a single valid PostgreSQL read-only query is supported.",
            retryable=False,
        ) from exc

    if len(statements) != 1:
        raise MCPToolError(
            code="invalid_query",
            message="Only a single SQL statement is allowed.",
            retryable=False,
        )

    statement = statements[0]
    if not isinstance(statement, ALLOWED_STATEMENT_TYPES):
        raise MCPToolError(
            code="invalid_query",
            message="Only read-only SELECT queries are supported.",
            retryable=False,
        )

    if LOCKING_CLAUSE_RE.search(normalized_input):
        raise MCPToolError(
            code="invalid_query",
            message="Row-locking clauses are not allowed.",
            retryable=False,
        )

    if ADVISORY_LOCK_RE.search(normalized_input):
        raise MCPToolError(
            code="invalid_query",
            message="Locking helper functions are not allowed.",
            retryable=False,
        )

    if _contains_disallowed_expressions(statement):
        raise MCPToolError(
            code="invalid_query",
            message="The SQL statement contains commands that are not allowed by this MCP server.",
            retryable=False,
        )

    existing_limit = _extract_existing_limit(statement)
    limit_applied = min(existing_limit, limit) if existing_limit is not None else limit
    limited_statement = statement.limit(limit_applied, copy=True)

    return NormalizedQuery(
        sql=limited_statement.sql(dialect="postgres"),
        limit_applied=limit_applied,
    )
