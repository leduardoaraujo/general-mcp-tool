"""
MCP Prompts

Prompts reutilizáveis para fluxos comuns de interação.
"""

from mcp.server.fastmcp import FastMCP

EXPLORE_DATABASE_PROMPT = """
Você está ajudando a explorar um banco de dados PostgreSQL.

## Contexto Atual

Você tem acesso a:
- Lista de tabelas (pg_list_tables)
- Descrição de tabelas (pg_describe_table)
- Schema completo via resources (resource://schema/overview)
- Diretrizes de consulta (resource://guidelines/querying)

## Tarefa

Explore o banco de dados para entender:
1. Quais tabelas existem e seus propósitos
2. Como as tabelas se relacionam (foreign keys)
3. Quais dados estão disponíveis
4. Qual é o volume de dados em cada tabela

## Saída Esperada

Forneça um resumo estruturado:
- Principais entidades (tabelas centrais)
- Relacionamentos entre entidades
- Métricas de volume
- Sugestões de análises interessantes

Use ferramentas para descobrir o schema, não faça suposições.
"""

GENERATE_SAFE_SQL_PROMPT = """
Você está gerando SQL segura para PostgreSQL.

## Contexto

O usuário fez uma pergunta e você precisa gerar uma query SQL para respondê-la.
Você tem acesso ao schema do banco via resources e tools de descoberta.

## Regras Obrigatórias

1. NUNCA use SELECT * - especifique todas as colunas
2. SEMPRE use LIMIT (padrão: 100, máximo: 5000)
3. Valide nomes de tabelas e colunas antes de usar
4. Use aliases descritivos para tabelas
5. Adicione comentários para queries complexas
6. Prefira JOINs explícitos com ON clause

## Fluxo

1. Analise a pergunta do usuário
2. Identifique as tabelas relevantes (use find_relevant_tables se necessário)
3. Verifique a estrutura das tabelas (pg_describe_table)
4. Monte a query seguindo as regras
5. Explique suas premissas

## Saída

Forneça:
- SQL gerada (formatada)
- Explicação da lógica
- Premissas feitas
- Limitações conhecidas
"""

EXPLAIN_TABLE_PROMPT = """
Você está explicando a estrutura e propósito de uma tabela.

## Contexto

Você recebeu informações sobre uma tabela do banco de dados e precisa
explicar seu propósito e uso de forma clara.

## Informações Disponíveis

- Nome da tabela e schema
- Colunas (nome, tipo, nullable, default, PK)
- Chaves estrangeiras (relacionamentos)
- Índices disponíveis
- Comentários do banco
- Estimativa de linhas

## Tarefa

Explique:
1. O que representa esta tabela (conceito de negócio)
2. Principais colunas e seus significados
3. Relacionamentos com outras tabelas
4. Como esta tabela é tipicamente usada
5. Considerações importantes (performance, nulls, etc.)

## Estilo

- Use linguagem clara e acessível
- Evite jargões técnicos quando possível
- Relacione com conceitos de negócio
- Dê exemplos de uso quando apropriado
"""

ANALYZE_QUESTION_PROMPT = """
Você está analisando uma pergunta para determinar como respondê-la usando dados.

## Contexto

Um usuário fez uma pergunta em linguagem natural. Você precisa:
1. Entender o que ele quer saber
2. Identificar quais dados são necessários
3. Determinar se é possível responder com o schema atual
4. Planejar a abordagem de consulta

## Análise Necessária

Para cada pergunta, analise:
- **Intenção**: O que o usuário realmente quer saber?
- **Entidades**: Quais objetos de negócio estão envolvidos?
- **Métricas**: Que cálculos ou agregações são necessários?
- **Filtros**: Que restrições de dados devem ser aplicadas?
- **Ordenação**: Como os resultados devem ser ordenados?
- **Temporalidade**: Há restrições de período?

## Resolução de Ambiguidade

Se a pergunta for ambígua:
1. Identifique as possíveis interpretações
2. Escolha a mais provável
3. Explique sua interpretação
4. Ofereça alternativas se relevante

## Saída

Forneça:
- Interpretação clara da pergunta
- Entidades identificadas
- Tabelas candidatas (com justificativa)
- Estratégia de consulta recomendada
- Possíveis limitações
"""


def register_prompts(mcp: FastMCP) -> None:
    """Registra prompts reutilizáveis."""

    @mcp.prompt(name="explore_database")
    async def explore_database_prompt() -> str:
        """
        Prompt para explorar e entender a estrutura do banco de dados.
        Use este prompt quando o usuário quer entender o que está disponível.
        """
        return EXPLORE_DATABASE_PROMPT

    @mcp.prompt(name="generate_safe_sql")
    async def generate_safe_sql_prompt() -> str:
        """
        Prompt para gerar SQL segura a partir de uma pergunta.
        Use este prompt para criar queries seguindo as diretrizes.
        """
        return GENERATE_SAFE_SQL_PROMPT

    @mcp.prompt(name="explain_table")
    async def explain_table_prompt() -> str:
        """
        Prompt para explicar uma tabela e seu propósito.
        Use este prompt para descrever tabelas de forma amigável.
        """
        return EXPLAIN_TABLE_PROMPT

    @mcp.prompt(name="analyze_question")
    async def analyze_question_prompt() -> str:
        """
        Prompt para analisar uma pergunta do usuário.
        Use este prompt para planejar como responder uma consulta.
        """
        return ANALYZE_QUESTION_PROMPT
