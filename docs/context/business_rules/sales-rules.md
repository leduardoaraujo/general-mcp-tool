# Sales Business Rules

Tags: sales, revenue, analytics, postgresql

Revenue must be calculated from confirmed orders only.

Cancelled orders are excluded from sales totals, margin calculations, and semantic model measures.

Gross margin is calculated as revenue minus cost of goods sold.

When a request asks for sales performance, include the sales date, customer segment, and product category when available.
