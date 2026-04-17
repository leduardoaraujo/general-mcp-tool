# System Context

## Nome do Sistema

MCP Orchestrator

## Objetivo

Criar um servidor MCP capaz de:

- interpretar solicitacoes do usuario
- enriquecer contexto com documentos
- delegar execucao para MCPs especializados
- consolidar respostas em um contrato unico

## Motivacao

Ambientes analiticos corporativos sao fragmentados.

Informacoes costumam estar distribuidas entre:

- modelos semanticos
- bancos de dados
- planilhas
- APIs
- documentacao interna

Usuarios precisam navegar manualmente por multiplos sistemas para encontrar dados, entender regras e executar tarefas.

O MCP Orchestrator atua como camada unificada de acesso inteligente, mantendo o pedido do usuario dentro de um fluxo controlado de interpretacao, contexto, roteamento e normalizacao.

## Componentes

### MCP Principal

Entrada unica do sistema.

Responsavel por:

- receber solicitacoes
- coordenar execucao
- manter rastreabilidade
- consolidar resultados

### Request Understanding

Extrai estrutura da solicitacao.

Campos principais:

- intent
- domain
- task_type
- candidate_mcps
- constraints

### RAG Middleware

Recupera contexto relevante de documentos.

Fontes possiveis:

- regras de negocio
- schemas
- documentacao tecnica
- exemplos
- playbooks operacionais

### Context Composer

Constroi a request enriquecida.

Inclui:

- pedido original
- interpretacao estruturada
- contexto recuperado
- restricoes
- instrucoes de execucao

### Router

Decide qual MCP executar.

Possibilidades:

- execucao simples
- execucao composta
- execucao sequencial
- execucao paralela
- fallback

### MCP Clients

Adapters para servidores MCP especializados.

Inicialmente:

- Power BI
- PostgreSQL
- SQL Server
- Excel

### Response Normalizer

Transforma respostas heterogeneas em um formato comum para o consumidor final.

## Diretorio Futuro de Documentos RAG

```text
docs/
  business_rules/
  schemas/
  examples/
  playbooks/
```

Esse diretorio sera usado pelo RAG Middleware para montar contexto operacional antes de qualquer chamada para MCP especializado.

## Principios Arquiteturais

1. contratos explicitos entre camadas
2. baixo acoplamento entre componentes
3. composicao ao inves de heranca
4. contexto obrigatorio antes da execucao
5. rastreabilidade de decisoes
6. arquitetura extensivel para novos MCPs
7. observabilidade desde os fluxos principais

## Restricoes Tecnicas

- Python 3.11+
- modelos de contrato com Pydantic
- nomes de codigo em ingles
- controllers sem logica de negocio
- logs estruturados por request
- integracoes externas atras de adapters

## Decisoes Provisorias

- O MCP Orchestrator sera desenvolvido neste repositorio.
- A documentacao operacional sera versionada em `docs/`.
- O pedido cru do usuario nunca sera enviado diretamente para um MCP especializado.
- MCPs especializados serao acessados por clients/adapters.
- A Fase 1 deve iniciar pelo intake e entendimento estruturado da request.

## Criterios de Sucesso

- adicionar novo MCP sem refatorar o nucleo
- modificar o RAG Middleware sem alterar o router
- interpretar pedidos de multiplos dominios
- manter fluxo observavel e auditavel
- preservar contratos explicitos entre as camadas
- permitir testes isolados de cada componente
