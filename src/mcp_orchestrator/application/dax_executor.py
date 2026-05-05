"""DAX query generator for Power BI measure queries."""

from datetime import datetime
from typing import Any

from mcp_orchestrator.application.power_bi_measures import MeasureContext


class DaxQueryGenerator:
    """Generate DAX queries based on measure context and filters."""
    
    @staticmethod
    def generate_query(context: MeasureContext) -> str:
        """
        Generate a DAX query string for the given measure context.
        
        Examples:
            Simple measure without filter:
                EVALUATE SUMMARIZECOLUMNS('Calendar'[Month], "Value", [Movimentacao Periodo])
            
            With date filter (February 2026):
                EVALUATE SUMMARIZECOLUMNS(
                    FILTER('Calendar', 'Calendar'[Month] = 2 && 'Calendar'[Year] = 2026),
                    "Value", [Movimentacao Periodo]
                )
        """
        measure_name = context.measure.internal_name
        date_filter = context.date_filter
        
        if not date_filter:
            # Simple query without filters
            return f"EVALUATE {{{measure_name}}}"
        
        # Build filter conditions
        filter_conditions = DaxQueryGenerator._build_filter_conditions(date_filter)
        
        # Build the full query
        if filter_conditions:
            query = f"""EVALUATE
CALCULATETABLE(
    SUMMARIZECOLUMNS(
        'Calendar'[Year],
        'Calendar'[Month],
        "Valor", [{measure_name}]
    ),
    {filter_conditions}
)"""
        else:
            query = f"EVALUATE {{{measure_name}}}"
        
        return query
    
    @staticmethod
    def _build_filter_conditions(date_filter: dict[str, Any]) -> str:
        """Build DAX filter conditions from date filter dictionary."""
        conditions = []
        
        year = date_filter.get("year")
        month = date_filter.get("month")
        quarter = date_filter.get("quarter")
        
        if year:
            conditions.append(f"'Calendar'[Year] = {year}")
        
        if month:
            conditions.append(f"'Calendar'[Month] = {month}")
        
        if quarter:
            # Q1: months 1-3, Q2: 4-6, Q3: 7-9, Q4: 10-12
            quarter_months = {
                1: (1, 2, 3),
                2: (4, 5, 6),
                3: (7, 8, 9),
                4: (10, 11, 12),
            }
            start_month, mid_month, end_month = quarter_months[quarter]
            conditions.append(
                f"'Calendar'[Month] IN ({start_month}, {mid_month}, {end_month})"
            )
        
        if not conditions:
            return ""
        
        return " AND ".join(conditions)
    
    @staticmethod
    def generate_simple_dax_query(measure_name: str, year: int | None = None, month: int | None = None) -> str:
        """
        Generate a simple DAX query for a measure with optional date filters.
        More straightforward version for common cases.
        """
        filters = []
        
        if year:
            filters.append(f"'Calendar'[Year] = {year}")
        if month:
            filters.append(f"'Calendar'[Month] = {month}")
        
        if filters:
            filter_expr = " AND ".join(filters)
            return f"""EVALUATE
CALCULATE(
    [{measure_name}],
    {filter_expr}
)"""
        else:
            return f"EVALUATE CALCULATE([{measure_name}])"
    
    @staticmethod
    def generate_tabular_dax_query(
        measure_name: str,
        year: int | None = None,
        month: int | None = None,
        group_by_date: bool = True,
    ) -> str:
        """
        Generate a tabular DAX query that returns results with date dimensions.
        Useful for seeing breakdown by date.
        """
        filters = []
        grouping = "'Calendar'[Year], 'Calendar'[Month]" if group_by_date else ""
        
        if year:
            filters.append(f"'Calendar'[Year] = {year}")
        if month:
            filters.append(f"'Calendar'[Month] = {month}")
        
        filter_expr = " AND ".join(filters) if filters else ""
        
        if grouping:
            if filter_expr:
                return f"""EVALUATE
SUMMARIZECOLUMNS(
    {grouping},
    FILTER(ALL('Calendar'), {filter_expr}),
    "Valor", [{measure_name}]
)"""
            else:
                return f"""EVALUATE
SUMMARIZECOLUMNS(
    {grouping},
    "Valor", [{measure_name}]
)"""
        else:
            if filter_expr:
                return f"""EVALUATE
CALCULATE(
    [{measure_name}],
    {filter_expr}
)"""
            else:
                return f"EVALUATE [{measure_name}]"


class PowerBiQueryExecutor:
    """Handle execution of DAX queries via MCP."""
    
    def __init__(self, mcp_proxy):
        """Initialize with reference to MCP proxy client."""
        self.mcp_proxy = mcp_proxy
    
    async def execute_dax_query(self, dax_query: str) -> dict[str, Any]:
        """
        Execute a DAX query through the Power BI MCP.
        Returns the query results or error information.
        """
        try:
            result = await self.mcp_proxy.call_powerbi_tool(
                "dax_query_operations",
                {
                    "operation": "execute_query",
                    "query": dax_query,
                }
            )
            return result
        except Exception as e:
            return {
                "ok": False,
                "error": f"Failed to execute DAX query: {str(e)}",
                "query": dax_query,
            }
    
    async def preview_dax_query(self, dax_query: str) -> dict[str, Any]:
        """
        Get a preview of the DAX query without executing it.
        Useful for validation and understanding.
        """
        return {
            "ok": True,
            "query": dax_query,
            "type": "dax_query",
            "note": "This is a preview. Call execute_dax_query to get results.",
        }
