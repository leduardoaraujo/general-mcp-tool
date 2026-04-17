# Sales Schema

Tags: sales, schema, sql, postgresql, sql_server

The analytics schema contains these core tables:

- `sales_orders`: order_id, customer_id, product_id, order_date, status, revenue, cost
- `customers`: customer_id, customer_name, segment, region
- `products`: product_id, product_name, category

The Power BI semantic model exposes measures:

- `Total Sales`
- `Gross Margin`
- `Order Count`

Use `sales_orders.status = 'confirmed'` for governed revenue queries.
