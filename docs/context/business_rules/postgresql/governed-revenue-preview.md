# Governed Revenue Preview

Rule ID: postgresql.governed_revenue_preview
Domain: postgresql
Tags: postgresql, analytics, sql, revenue, business_rules
Applies To: PostgreSQL revenue analysis and SQL preview requests.
Business Definition: Governed revenue uses confirmed sales orders only and excludes cancelled orders from totals, margins, and comparison metrics.
Data Sources: `sales_orders`, `sales_order_items`, and related dimensional tables described in `docs/context/schemas`.
SQL/DAX Guidance: SQL previews must filter `sales_orders.status = 'confirmed'` before calculating revenue or margin.
Validation Notes: Compare generated SQL against the schema document and keep `auto_execute=false` unless a pending confirmation authorizes read-only execution.
Owner: Analytics Engineering
Last Reviewed: 2026-05-05

Use this rule whenever a user asks for revenue, sales totals, margin, or monthly sales analysis through PostgreSQL.
