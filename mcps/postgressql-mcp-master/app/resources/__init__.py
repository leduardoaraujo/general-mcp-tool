"""
Resources MCP para o servidor semântico PostgreSQL.
"""

from app.resources.examples import register_example_resources
from app.resources.guidelines import register_guideline_resources
from app.resources.schema import register_schema_resources

__all__ = [
    "register_example_resources",
    "register_guideline_resources",
    "register_schema_resources",
]
