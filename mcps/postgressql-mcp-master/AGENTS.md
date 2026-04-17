# PostgreSQL Semantic MCP

Um servidor **MCP (Model Context Protocol)** que transforma bancos PostgreSQL em interfaces semânticas inteligentes para dados.

## Objetivo

Permitir que usuários explorem e consultem dados usando **linguagem natural**, sem precisar conhecer o schema, nomes de tabelas ou escrever SQL manualmente.

## Funcionalidades Principais

### 1. Descoberta Automática do Schema (FASE 1)

Ao iniciar, o servidor automaticamente:
- Consulta `information_schema` e `pg_catalog`
- Mapeia schemas, tabelas, colunas, tipos
- Captura comentários e relacionamentos
- Indexa para busca semântica

```
DatabaseMap
 ├─ schemas
 │   ├─ tables
 │   │   ├─ columns
 │   │   ├─ types
 │   │   ├─ comments
 │   │   ├─ foreign_keys
 │   │   └─ indexes
```

### 2. Resources MCP (FASE 2)

Contexto disponível via resources:

| Resource | Descrição |
|----------|-----------|
| `resource://guidelines/querying` | Diretrizes para consultas seguras |
| `resource://guidelines/safety` | Regras de segurança |
| `resource://domains/general` | Contexto geral de uso |
| `resource://schema/overview` | Visão geral do schema |
| `resource://schema/{db}/{schema}/{table}` | Detalhes de uma tabela |
| `resource://schema/json` | Schema completo em JSON |
| `resource://examples/queries` | Exemplos de SQL |

### 3. Prompts MCP (FASE 3)

Prompts reutilizáveis:

- `explore_database` - Explorar a estrutura do banco
- `generate_safe_sql` - Gerar SQL segura
- `explain_table` - Explicar uma tabela
- `analyze_question` - Analisar uma pergunta

### 4. Tools Semânticas de Alto Nível (FASE 4)

Novas ferramentas orientadas a intenção:

#### `discover_database_context`
Identifica quais partes do banco podem responder a uma pergunta.

```json
{
  "question": "quantos colaboradores ativos temos?"
}
```

#### `find_relevant_tables`
Encontra tabelas e colunas relevantes para uma pergunta.

#### `generate_safe_sql`
Gera SQL segura a partir de linguagem natural (apenas gera, não executa).

#### `run_guided_query`
Fluxo completo: pergunta → tabelas → SQL → validação → execução → resumo.

### 5. Mapeamento Semântico (FASE 5)

Traduz termos humanos para referências de banco:

| Termo Humano | Pode Significar |
|--------------|-----------------|
| colaborador | employee, funcionario, pessoa |
| cliente | customer, buyer |
| produto | product, item |
| pedido | order, venda, sale |
| pagamento | payment |
| endereco | address, location |

O sistema usa:
- Heurística baseada em nome
- Stemming (português/inglês)
- Expansão de sinônimos

### 6. RAG Opcional (FASE 6)

Suporte opcional a recuperação semântica:

```bash
# Instale dependências opcionais
pip install sentence-transformers numpy
```

Funcionalidades:
- Indexação de descrições de tabelas/colunas
- Busca semântica de exemplos de queries
- Glossário de negócio

## Diretrizes de Segurança (Aplicadas)

Todas as queries são validadas automaticamente:

- ✅ Nunca permite `SELECT *` (especifica colunas)
- ✅ Sempre aplica `LIMIT` (padrão: 100, máx: 5000)
- ✅ Valida schema antes de executar
- ✅ Apenas operações READ-ONLY
- ✅ Protege contra múltiplos statements
- ✅ Timeouts configuráveis

## Configuração

### Mínima (Zero Config)

```bash
export POSTGRES_DSN="postgresql://user:pass@host:5432/db"
python server.py
```

### Múltiplos Bancos

```bash
export POSTGRES_DB_1_NAME="production"
export POSTGRES_DB_1_DSN="postgresql://user:pass@host:5432/prod"
export POSTGRES_DB_2_NAME="analytics"
export POSTGRES_DB_2_DSN="postgresql://user:pass@host:5432/analytics"
```

### Variáveis Opcionais

```bash
# Pool
export POOL_MIN_SIZE=1
export POOL_MAX_SIZE=3

# Timeouts
export QUERY_STATEMENT_TIMEOUT_MS=10000
export QUERY_LOCK_TIMEOUT_MS=1000
```

## Uso com Clientes MCP

### Exemplo com Claude Desktop

```json
{
  "mcpServers": {
    "postgres": {
      "command": "python",
      "args": ["/caminho/para/server.py"],
      "env": {
        "POSTGRES_DSN": "postgresql://user:pass@localhost/mydb"
      }
    }
  }
}
```

### Exemplo de Interação

Usuário:
> "Quantos pedidos foram feitos ontem?"

Servidor MCP:
1. Usa `discover_database_context` para identificar tabelas relevantes
2. Encontra tabela de "pedidos" via mapeamento semântico
3. Gera SQL segura com filtros de data
4. Executa e retorna resultado com preview

## Estrutura do Projeto

```
postgressql-mcp/
├── server.py                  # Ponto de entrada
├── core/                      # Lógica core existente
│   ├── connection.py         # Gerenciamento de conexões
│   ├── query_validation.py   # Validação de queries
│   ├── errors.py             # Tratamento de erros
│   ├── formatters.py         # Formatação de resultados
│   └── tool_results.py       # Estruturas de resultado
├── tools/                     # Tools existentes (baixo nível)
│   ├── schema.py             # pg_list_tables, pg_describe_table
│   └── query.py              # pg_execute_query
├── app/                       # Novo: funcionalidades semânticas
│   ├── services/             # Serviços internos
│   │   ├── discovery.py      # DatabaseMap, descoberta de schema
│   │   ├── semantic_mapper.py # Mapeamento termos → tabelas
│   │   └── rag.py            # Recuperação semântica (opcional)
│   ├── resources/            # Resources MCP
│   │   ├── guidelines.py     # Diretrizes de uso
│   │   ├── schema.py         # Schema como resources
│   │   └── examples.py       # Exemplos de queries
│   ├── prompts/              # Prompts MCP
│   │   └── queries.py        # Prompts reutilizáveis
│   └── semantic_tools/       # Tools de alto nível
│       └── high_level.py     # discover_database_context, etc.
└── tests/                    # Testes
```

## Instalação

```bash
# Básica
pip install -r requirements.txt

# Com RAG (opcional)
pip install -r requirements.txt sentence-transformers numpy
```

## Desenvolvimento

### Executar Testes

```bash
pytest tests/
```

### Formatação

```bash
ruff format .
ruff check --fix .
```

## Principios de Design

1. **Zero Configuração**: Usuário só precisa do DSN
2. **Segurança por Padrão**: Todas as queries validadas
3. **Queries Pequenas**: LIMIT automático
4. **Explicabilidade**: Premissas claras
5. **Descoberta Automática**: Schema mapeado automaticamente
6. **Interface Semântica**: Linguagem natural

## Logs

IMPORTANTE: O servidor usa **stdio** para comunicação MCP.

- **stdout**: Apenas mensagens JSON-RPC do protocolo MCP
- **stderr**: Logs e informações de debug

Nunca escreva logs em stdout!

## Contribuindo

1. Mantenha compatibilidade com MCP
2. Siga as diretrizes de segurança
3. Adicione testes para novas features
4. Documente novas tools e resources

## Licença

MIT
