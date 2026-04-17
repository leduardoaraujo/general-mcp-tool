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
    PLAYBOOK = "playbook"
    EXAMPLE = "example"
    UNKNOWN = "unknown"


class ResultStatus(str, Enum):
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    ERROR = "error"
