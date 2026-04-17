# General MCP Tool

Projeto Python com dois modulos principais:

- `powerbi_mcp_manager`: instala e atualiza localmente o pacote npm `@microsoft/powerbi-modeling-mcp`.
- `mcp_orchestrator`: API FastAPI para orquestracao de requests com intake, RAG local, roteamento de clients MCP e normalizacao de resposta.

## Visao Geral

Este repositorio centraliza:

- gerenciamento de versao e configuracao do Power BI Modeling MCP em pasta controlada;
- orquestracao de requests com contexto vindo de arquivos em `docs/`;
- uma base inicial para evoluir fluxos de analise orientados a regras de negocio.

## Requisitos

- Python 3.11+
- Node.js + npm no PATH (necessario para o `powerbi_mcp_manager`)
- Acesso ao registro npm

## Instalacao

No diretorio raiz do projeto:

```powershell
python -m pip install -e .
```

Dependencias de desenvolvimento (testes):

```powershell
python -m pip install -e .[dev]
```

## Modulo 1: Power BI MCP Manager

Responsavel por instalar o pacote npm em area local do projeto.

- pasta de instalacao padrao: `mcps/powerbi-modeling-mcp`
- cache npm padrao: `.npm-cache`

### Comandos CLI

Depois de instalar o projeto com `pip install -e .`:

```powershell
powerbi-mcp-manager status
powerbi-mcp-manager install
powerbi-mcp-manager update
powerbi-mcp-manager check
powerbi-mcp-manager path
powerbi-mcp-manager config
```

Sem instalar como script de entrypoint:

```powershell
python scripts/powerbi_mcp_manager.py status
python scripts/powerbi_mcp_manager.py install
python scripts/powerbi_mcp_manager.py update
python scripts/powerbi_mcp_manager.py check
python scripts/powerbi_mcp_manager.py path
python scripts/powerbi_mcp_manager.py config
```

### Codigos de saida do `check`

- `0`: instalado e atualizado
- `1`: instalado, mas com atualizacao disponivel
- `2`: nao instalado

### Uso em codigo Python

```python
from powerbi_mcp_manager import PowerBiMcpManager

manager = PowerBiMcpManager(project_dir=r"C:\my-project")

status = manager.status()
print(status.state)
print(status.latest_version)

if status.state != "up-to-date":
    manager.update()

config = manager.mcp_config()
print(config)
```

### Variaveis de ambiente (manager)

- `POWERBI_MCP_PACKAGE`: pacote npm alvo (padrao: `@microsoft/powerbi-modeling-mcp`)
- `POWERBI_MCP_TAG`: dist-tag acompanhada (padrao: `latest`)
- `POWERBI_MCP_DIR`: pasta local de instalacao
- `POWERBI_MCP_NPM_CACHE`: pasta local de cache do npm

Exemplo:

```powershell
$env:POWERBI_MCP_TAG = "latest"
powerbi-mcp-manager update
```

## Modulo 2: MCP Orchestrator

API FastAPI com pipeline:

1. Intake e interpretacao da solicitacao.
2. Recuperacao de contexto local (RAG textual) a partir de `docs/`.
3. Composicao da request enriquecida.
4. Roteamento para clients MCP.
5. Normalizacao da resposta final.

### Executar API

Opcao 1 (desenvolvimento com reload):

```powershell
python -m uvicorn mcp_orchestrator.main:app --app-dir src --reload
```

Opcao 2 (entrypoint do projeto):

```powershell
mcp-orchestrator
```

Servidor padrao: `http://127.0.0.1:8000`

### Endpoints

- `GET /health`
- `POST /orchestrate`
- `GET /docs-index/status`
- `POST /docs-index/rebuild`
- `GET /mcp-servers/status`

### Exemplo de request

```json
{
  "message": "Show Total Sales from the Power BI semantic model",
  "domain_hint": "sales",
  "tags": ["powerbi", "sales"],
  "metadata": {}
}
```

### Exemplo via PowerShell

```powershell
$body = @{
  message = "Show Total Sales from the Power BI semantic model"
  domain_hint = "sales"
  tags = @("powerbi", "sales")
  metadata = @{}
} | ConvertTo-Json

Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/orchestrate" `
  -ContentType "application/json" `
  -Body $body
```

### Variaveis de ambiente (orchestrator)

- `MCP_ORCHESTRATOR_PROJECT_DIR`: pasta base do projeto para resolucao de caminhos.
- `MCP_ORCHESTRATOR_DOCS_DIR`: pasta de documentos para indexacao RAG.
- `MCP_ORCHESTRATOR_MCPS_DIR`: pasta de servidores MCP locais.

Se `MCP_ORCHESTRATOR_DOCS_DIR` nao for definido, o padrao e `<project_dir>/docs`.
Se `MCP_ORCHESTRATOR_MCPS_DIR` nao for definido, o padrao e `<project_dir>/mcps`.

### Pasta `mcps/`

Servidores MCP especializados podem ficar em `mcps/`, cada um em sua propria
pasta, com um `server.py` como ponto de entrada.

Exemplo:

```text
mcps/
  powerbi-modeling-mcp/
    package.json
    package-lock.json
    node_modules/
  postgressql-mcp-master/
    server.py
    pyproject.toml
    requirements.txt
```

O orchestrator nao importa o codigo desses servidores diretamente. Servidores
Python sao tratados como processos `python server.py`; servidores npm, como o
Power BI Modeling MCP, sao tratados pelo binario instalado em `node_modules/.bin`.

Para ver quais servidores locais foram descobertos:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/mcp-servers/status
```

## Testes

Executar suite:

```powershell
pytest
```

## Estrutura (resumo)

- `src/powerbi_mcp_manager/`: manager e CLI
- `src/mcp_orchestrator/`: API, dominio, aplicacao, infraestrutura e normalizacao
- `docs/`: base de conhecimento para RAG e material de negocio/arquitetura
- `tests/`: testes automatizados

## Observacoes

- O estado do pacote gerenciado pode ser: `not-installed`, `up-to-date` ou `update-available`.
- O endpoint `POST /docs-index/rebuild` permite reconstruir o indice de documentos sem reiniciar a API.
- O endpoint `GET /mcp-servers/status` lista servidores MCP locais descobertos em `mcps/`.
