# Sales Query Examples

Tags: sales, examples, sql, excel

PostgreSQL example:

```sql
select date_trunc('month', order_date) as sales_month,
       sum(revenue) as total_sales
from sales_orders
where status = 'confirmed'
group by 1;
```

Excel extraction example:

- read worksheet `Orders`
- filter status to `confirmed`
- group by region and category
