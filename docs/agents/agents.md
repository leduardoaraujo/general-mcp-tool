# Agents

Este documento define os agentes responsaveis pelas diferentes partes do sistema.

Os agentes representam papeis operacionais usados durante desenvolvimento assistido por IA. Eles nao sao necessariamente processos em runtime; sao responsabilidades de trabalho e revisao.

## Architect Agent

Responsavel pela arquitetura do sistema.

Funcoes:

- definir boundaries entre modulos
- manter baixo acoplamento
- revisar contratos
- validar decisoes arquiteturais
- evitar overengineering
- manter consistencia entre specs

## Backend Agent

Responsavel pela implementacao do sistema.

Funcoes:

- criar servicos
- implementar rotas
- definir modelos Pydantic
- manter organizacao modular
- implementar logica de orquestracao
- respeitar separacao entre camadas

## RAG Agent

Responsavel pelo mecanismo de recuperacao de contexto.

Funcoes:

- definir estrutura de documentos
- implementar ingestao e indexacao
- definir chunking
- implementar retrieval
- definir filtros por dominio
- validar qualidade do contexto recuperado

## MCP Integration Agent

Responsavel pela integracao com MCPs especializados.

Funcoes:

- criar adapters
- padronizar contratos de execucao
- lidar com erros de execucao
- implementar fallback
- isolar detalhes dos MCPs externos

## QA Agent

Responsavel por qualidade e testes.

Funcoes:

- testes unitarios
- testes de integracao
- validacao de contratos
- cenarios de erro
- cobertura de regressao para fluxos criticos

## Docs Agent

Responsavel pela documentacao operacional.

Funcoes:

- manter specs
- registrar decisoes arquiteturais
- salvar prompts utilizados
- atualizar roadmap
- garantir rastreabilidade entre fases
