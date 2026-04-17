"""
MCP Resources - Guidelines

Exposição de diretrizes e regras de uso através de resources MCP.
Estes resources são automaticamente disponibilizados para o cliente.
"""

from mcp.server.fastmcp import FastMCP

# Diretrizes de consulta
QUERYING_GUIDELINES = """
# Diretrizes de Consulta ao Banco de Dados

## Regras Obrigatórias

1. **NUNCA usar SELECT ***
   - Sempre especifique as colunas necessárias
   - Isso melhora performance e evita exposição de dados desnecessários

2. **SEMPRE usar LIMIT por padrão**
   - Aplique LIMIT em todas as consultas
   - Comece com limites pequenos (100-1000) para exploração
   - Aumente gradualmente conforme necessário

3. **Validar Schema antes de Consultar**
   - Use pg_describe_table para entender a estrutura
   - Verifique nomes de colunas e tipos de dados
   - Confirme relacionamentos via foreign keys

4. **Explicar Premissas quando houver Ambiguidade**
   - Se a pergunta puder ser interpretada de múltiplas formas, esclareça
   - Indique quais tabelas e colunas serão usadas
   - Peça confirmação antes de executar queries grandes

5. **Evitar Consultas que Retornem Milhões de Linhas**
   - Use filtros apropriados (WHERE)
   - Considere agregações para dados sumarizados
   - Quebre consultas grandes em partes menores

## Boas Práticas

- Use aliases descritivos para tabelas
- Prefira JOINs explícitos
- Adicione comentários em queries complexas
- Ordene resultados quando relevante
- Use índices disponíveis para filtros comuns
"""

# Diretrizes de segurança
SAFETY_GUIDELINES = """
# Diretrizes de Segurança

## Princípios Fundamentais

1. **Segurança por Padrão**
   - Todas as queries são validadas antes da execução
   - Apenas operações READ-ONLY são permitidas
   - Modificações no banco são bloqueadas

2. **Queries Pequenas e Seguras**
   - LIMIT é aplicado automaticamente
   - Timeouts protegem contra queries longas
   - Statements múltiplos são rejeitados

3. **Validação de Schema**
   - Nomes de tabelas são verificados antes da execução
   - SQL injection é prevenido via prepared statements
   - Apenas schemas visíveis são acessíveis

4. **Proteção de Dados**
   - Preview obrigatório para grandes resultados
   - Logs não expõem dados sensíveis
   - Conexões usam transações READ ONLY

## Limites de Segurança

- **Statement timeout**: 10 segundos por padrão
- **Lock timeout**: 1 segundo
- **Máximo de linhas**: 5000 por consulta
- **Apenas SELECTs**: INSERT, UPDATE, DELETE bloqueados
- **Sem comandos DDL**: CREATE, DROP, ALTER bloqueados
"""

# Domínio geral
GENERAL_DOMAIN_CONTEXT = """
# Contexto de Domínio Geral

## Como usar este servidor MCP

Este servidor permite explorar e consultar bancos PostgreSQL usando linguagem natural.

### Fluxo de Trabalho Recomendado

1. **Descubra o Schema**
   - Use `pg_list_tables` para ver tabelas disponíveis
   - Use `pg_describe_table` para entender estruturas
   - Consulte resources de guidelines

2. **Explore com Linguagem Natural**
   - Use `discover_database_context` para entender o que está disponível
   - Use `find_relevant_tables` para identificar tabelas relevantes
   - Use `generate_safe_sql` para criar queries seguras

3. **Execute Consultas Guiadas**
   - Use `run_guided_query` para fluxo completo
   - Ou execute SQL gerada via `pg_execute_query`

### Dicas de Perguntas

- Seja específico sobre o que deseja saber
- Mencione períodos de tempo quando relevante
- Use termos do negócio (o mapeador semântico traduz)
- Pergunte sobre relacionamentos entre entidades

### Termos Comuns Mapeados

O sistema entende sinônimos para facilitar consultas:

- "colaborador" → employee, funcionario, pessoa
- "cliente" → customer, buyer
- "produto" → product, item
- "pedido" → order, venda, sale
- "pagamento" → payment
- "endereco" → address
"""


def register_guideline_resources(mcp: FastMCP) -> None:
    """Registra resources de diretrizes."""

    @mcp.resource("resource://guidelines/querying")
    async def get_querying_guidelines() -> str:
        """Retorna diretrizes para consultas seguras e eficientes."""
        return QUERYING_GUIDELINES

    @mcp.resource("resource://guidelines/safety")
    async def get_safety_guidelines() -> str:
        """Retorna diretrizes de segurança do servidor."""
        return SAFETY_GUIDELINES

    @mcp.resource("resource://domains/general")
    async def get_general_domain() -> str:
        """Retorna contexto geral de uso do servidor."""
        return GENERAL_DOMAIN_CONTEXT
