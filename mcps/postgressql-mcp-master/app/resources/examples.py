"""
MCP Resources - Query Examples

Exemplos de queries comuns para referência.
"""

from mcp.server.fastmcp import FastMCP

QUERY_EXAMPLES = """
# Exemplos de Queries

## Exploração Básica

### Listar todas as tabelas
```sql
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_type = 'BASE TABLE'
  AND table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY table_schema, table_name;
```

### Descrever uma tabela
```sql
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'nome_tabela'
  AND table_schema = 'public'
ORDER BY ordinal_position;
```

## Queries Comuns

### Top 10 registros mais recentes
```sql
SELECT col1, col2, col3
FROM minha_tabela
ORDER BY created_at DESC
LIMIT 10;
```

### Contagem por categoria
```sql
SELECT status, COUNT(*) as total
FROM pedidos
GROUP BY status
ORDER BY total DESC;
```

### Join entre tabelas
```sql
SELECT
    c.nome as cliente,
    p.data_pedido,
    p.valor_total
FROM clientes c
JOIN pedidos p ON p.cliente_id = c.id
WHERE p.data_pedido >= CURRENT_DATE - INTERVAL '30 days'
ORDER BY p.valor_total DESC
LIMIT 50;
```

### Agregação mensal
```sql
SELECT
    DATE_TRUNC('month', data_venda) as mes,
    COUNT(*) as total_vendas,
    SUM(valor) as receita_total
FROM vendas
WHERE data_venda >= CURRENT_DATE - INTERVAL '12 months'
GROUP BY DATE_TRUNC('month', data_venda)
ORDER BY mes;
```

### Subquery com CTE
```sql
WITH cliente_top AS (
    SELECT cliente_id, SUM(valor) as total_gasto
    FROM pedidos
    GROUP BY cliente_id
    ORDER BY total_gasto DESC
    LIMIT 10
)
SELECT
    c.nome,
    ct.total_gasto
FROM clientes c
JOIN cliente_top ct ON ct.cliente_id = c.id;
```

## Padrões de Busca

### Busca por texto
```sql
SELECT *
FROM produtos
WHERE nome ILIKE '%notebook%'
LIMIT 20;
```

### Busca por data
```sql
SELECT *
FROM eventos
WHERE data_evento BETWEEN '2024-01-01' AND '2024-12-31'
ORDER BY data_evento;
```

### Busca com múltiplos filtros
```sql
SELECT *
FROM pedidos
WHERE status = 'entregue'
  AND valor_total > 1000
  AND data_criacao >= CURRENT_DATE - INTERVAL '90 days'
ORDER BY valor_total DESC
LIMIT 25;
```

## Análise de Dados

### Estatísticas descritivas
```sql
SELECT
    COUNT(*) as total_registros,
    AVG(valor) as media,
    MIN(valor) as minimo,
    MAX(valor) as maximo,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY valor) as mediana
FROM vendas;
```

### Tendência temporal
```sql
SELECT
    DATE_TRUNC('week', data) as semana,
    COUNT(*) as eventos,
    AVG(valor) as media_valor
FROM registros
WHERE data >= CURRENT_DATE - INTERVAL '12 weeks'
GROUP BY 1
ORDER BY 1;
```
"""


def register_example_resources(mcp: FastMCP) -> None:
    """Registra resources de exemplos."""

    @mcp.resource("resource://examples/queries")
    async def get_query_examples() -> str:
        """Retorna exemplos de queries SQL comuns."""
        return QUERY_EXAMPLES
