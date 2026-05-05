from __future__ import annotations

from enum import Enum


class Domain(str, Enum):
    POWER_BI = "power_bi"
    POSTGRESQL = "postgresql"
    SQL_SERVER = "sql_server"
    EXCEL = "excel"
    ANALYTICS = "analytics"
    GENERAL = "general"
    UNKNOWN = "unknown"


class TaskType(str, Enum):
    SEMANTIC_MODEL_QUERY = "semantic_model_query"
    SEMANTIC_MODEL_INSPECTION = "semantic_model_inspection"
    MEASURE_VALUE_QUERY = "measure_value_query"
    DAX_QUERY = "dax_query"
    SQL_QUERY = "sql_query"
    TABULAR_EXTRACTION = "tabular_extraction"
    DOCUMENTATION_LOOKUP = "documentation_lookup"
    COMPOSITE = "composite"
    UNKNOWN = "unknown"


class McpTarget(str, Enum):
    POWER_BI = "power_bi"
    POSTGRESQL = "postgresql"
    SQL_SERVER = "sql_server"
    EXCEL = "excel"


class DocumentType(str, Enum):
    BUSINESS_RULE = "business_rule"
    SCHEMA = "schema"
    TECHNICAL_DOC = "technical_doc"
    PLAYBOOK = "playbook"
    EXAMPLE = "example"
    UNKNOWN = "unknown"


class ExecutionMode(str, Enum):
    SIMPLE = "simple"
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    PREVIEW_ONLY = "preview_only"


class RequestedAction(str, Enum):
    PREVIEW = "preview"
    READ = "read"
    WRITE = "write"
    INSPECT_SCHEMA = "inspect_schema"
    INSPECT_MODEL = "inspect_model"
    GENERATE_QUERY = "generate_query"
    EXECUTE_QUERY = "execute_query"
    REFRESH = "refresh"
    UNKNOWN = "unknown"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SafetyLevel(str, Enum):
    SAFE = "safe"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"


class ResultStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    ERROR = "error"
