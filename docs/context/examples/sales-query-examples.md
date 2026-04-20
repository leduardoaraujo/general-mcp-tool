# Sales Query Examples

Tags: sales, examples, sql, postgresql

PostgreSQL example:

```sql
select date_trunc('month', order_date) as sales_month,
       sum(revenue) as total_sales
from sales_orders
where status = 'confirmed'
group by 1;
```

For monthly revenue questions, start from `sales_orders`, filter confirmed orders, and group by the month of `order_date`.
