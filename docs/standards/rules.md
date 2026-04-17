# Project Rules

Estas regras definem os padroes obrigatorios do projeto.

## Linguagem

Python 3.11+.

## Tipagem

Tipagem forte obrigatoria.

Todos os modelos de dados entre camadas devem usar Pydantic.

## Arquitetura

Separacao clara de camadas:

- domain
- application
- infrastructure
- api

Cada camada deve depender apenas de contratos estaveis e responsabilidades explicitas.

## Controllers

Controllers nao contem logica de negocio.

Responsabilidades:

- receber request
- validar entrada
- chamar servicos
- retornar resposta no contrato definido

## Servicos

Toda logica de negocio reside em servicos da camada application.

Servicos devem coordenar casos de uso, sem depender diretamente de detalhes de infraestrutura.

## Funcoes

Funcoes devem ser pequenas.

Regra pratica:

- maximo aproximado de 50 linhas
- uma responsabilidade por funcao
- evitar parametros excessivos

## Nomeacao

Todos os nomes de codigo devem estar em ingles.

Isso inclui:

- arquivos Python
- classes
- funcoes
- variaveis
- modelos Pydantic
- contratos

## Comentarios

Comentarios devem ser minimos.

Preferir codigo autoexplicativo. Comentarios sao aceitaveis apenas para explicar decisoes nao obvias, restricoes externas ou comportamento delicado.

## Contratos

Todos os fluxos relevantes devem possuir contratos explicitos.

Exemplos:

- RequestInterpretation
- RAGContext
- EnrichedRequest
- MCPResult
- NormalizedResponse

Contratos entre camadas devem ser estaveis e testaveis.

## Regra Critica

O pedido do usuario nunca e enviado diretamente para um MCP especializado.

Sempre deve passar por:

1. interpretacao
2. recuperacao de contexto
3. composicao da request enriquecida
4. roteamento controlado

## Logging

Logs estruturados sao obrigatorios nos fluxos principais.

Cada request deve possuir:

- correlation_id
- trace das etapas executadas
- tempo de execucao
- erros normalizados

## Testes

Fluxos criticos devem possuir:

- testes unitarios
- testes de integracao
- validacao de contratos
- cenarios de erro

## Organizacao

Arquivos devem possuir responsabilidade clara.

Evitar arquivos grandes e genericos. Quando um arquivo acumular responsabilidades, ele deve ser dividido por dominio, camada ou caso de uso.

## Documentacao

Cada fase do projeto deve fechar com:

- spec
- prompt salvo
- implementacao
- checklist de aceite

Decisoes importantes devem ser registradas em documentacao versionada.
