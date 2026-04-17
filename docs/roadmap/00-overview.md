# MCP Orchestrator

## Visao Geral

Este projeto implementa um MCP Orchestrator Server, responsavel por atuar como gateway inteligente entre usuarios e multiplos servidores MCP especializados.

O sistema recebe solicitacoes do usuario, interpreta o pedido, recupera contexto relevante por meio de um mecanismo RAG baseado em documentos e delega execucao para MCPs especializados, como:

- Power BI
- PostgreSQL
- SQL Server
- Excel

A resposta final e normalizada e retornada ao usuario de forma consistente.

## Problema

Ferramentas analiticas normalmente possuem multiplos sistemas isolados:

- modelos semanticos
- bancos SQL
- planilhas
- APIs
- documentacao dispersa

Usuarios precisam navegar manualmente entre esses sistemas para resolver tarefas que deveriam partir de um unico pedido.

O objetivo deste projeto e criar um orquestrador MCP que centraliza essa interacao, permitindo que uma solicitacao seja interpretada, contextualizada e executada no sistema correto.

## Principio Central da Arquitetura

O MCP principal nao e apenas um router.

Ele atua como um gateway contextual.

Antes de qualquer execucao:

1. o pedido e interpretado
2. contexto relevante e recuperado
3. a request e enriquecida
4. somente entao e enviada para MCPs especializados

Nenhum MCP especializado recebe o pedido cru do usuario.

## Fluxo Geral

```text
Usuario
  |
MCP Principal
  |
Request Understanding
  |
RAG Middleware
  |
Context Composer
  |
Router / Orchestrator
  |
MCPs especializados
  |
Response Normalizer
  |
Resposta final
```

## Componentes Principais

### Request Understanding

Responsavel por interpretar o pedido e extrair:

- intent
- domain
- task_type
- candidate_mcps
- constraints

### RAG Middleware

Responsavel por recuperar contexto relevante a partir de um diretorio de documentos:

- regras de negocio
- schemas
- documentacao tecnica
- exemplos
- playbooks operacionais

### Context Composer

Responsavel por montar uma request enriquecida contendo:

- pedido original
- interpretacao estruturada
- contexto recuperado
- restricoes
- instrucoes de execucao

### MCP Router

Responsavel por decidir:

- qual MCP executar
- se a execucao sera simples, sequencial ou paralela
- estrategia de fallback

### MCP Clients

Adapters para MCPs especializados.

Inicialmente:

- Power BI
- PostgreSQL
- SQL Server
- Excel

### Response Normalizer

Responsavel por transformar respostas heterogeneas em um contrato unico de resposta.

## Objetivos do Projeto

- arquitetura modular
- baixo acoplamento
- contratos explicitos
- facil extensao para novos MCPs
- rastreabilidade completa das decisoes
- documentacao operacional desde o inicio

## Nao Objetivos

Este projeto nao implementa nesta fase:

- interface grafica
- logica de negocio especifica de uma empresa
- execucao direta sem contexto
- integracoes reais com todos os MCPs especializados

O sistema funciona como middleware de orquestracao contextual.

## Stack Inicial

- Python 3.11+
- FastAPI
- Pydantic
- Async IO
- RAG local baseado em diretorio de documentos

## Ordem Inicial de Trabalho

1. fechar documentacao e contratos da Fase 0
2. documentar a Fase 1 de intake
3. implementar contratos Pydantic iniciais
4. evoluir o RAG Middleware
5. implementar composer, router, clients, normalizacao, API, observabilidade e testes
