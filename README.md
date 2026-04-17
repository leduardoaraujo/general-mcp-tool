# General MCP Tool

Modulo Python para baixar, verificar e atualizar o pacote npm
`@microsoft/powerbi-modeling-mcp` em uma pasta controlada do projeto.

O pacote MCP e instalado em `.managed/powerbi-modeling-mcp`, e o cache do npm
fica em `.npm-cache`. As duas pastas sao ignoradas pelo Git.

## MCP Orchestrator

O projeto tambem inclui um MVP de MCP Orchestrator em `src/mcp_orchestrator`.

Ele expoe uma API FastAPI que recebe pedidos do usuario, interpreta intencao e
dominio, recupera contexto local em `docs/`, compoe uma request enriquecida,
roteia para MCP clients mockados e retorna uma resposta normalizada.

Rodar em desenvolvimento:

```powershell
python -m uvicorn mcp_orchestrator.main:app --app-dir src --reload
```

Endpoints iniciais:

- `GET /health`
- `POST /orchestrate`
- `GET /docs-index/status`
- `POST /docs-index/rebuild`

Exemplo de payload:

```json
{
  "message": "Show Total Sales from the Power BI semantic model"
}
```

## Requisitos

- Python 3.11 ou superior
- Node.js/npm disponivel no PATH
- Acesso ao registro npm

## Uso como modulo

```python
from powerbi_mcp_manager import PowerBiMcpManager

manager = PowerBiMcpManager(project_dir=r"C:\caminho\do\seu\app")

status = manager.status()
print(status.state)
print(status.latest_version)

if status.state != "up-to-date":
    manager.update()

config = manager.mcp_config()
```

Se o outro software instalar este projeto como dependencia, use:

```powershell
python -m pip install -e .
```

## Uso como script

Sem instalar o modulo:

```powershell
python scripts/powerbi_mcp_manager.py status
python scripts/powerbi_mcp_manager.py install
python scripts/powerbi_mcp_manager.py update
python scripts/powerbi_mcp_manager.py path
python scripts/powerbi_mcp_manager.py config
```

Depois de instalar com `pip install -e .`, tambem funciona:

```powershell
powerbi-mcp-manager status
powerbi-mcp-manager update
```

## Automacao

```powershell
python scripts/powerbi_mcp_manager.py check
```

Codigos de saida:

- `0`: instalado e atualizado
- `1`: instalado, mas existe atualizacao
- `2`: ainda nao instalado

## Dados retornados

`PowerBiMcpManager.status()` retorna um objeto `Status` com:

- `package_name`
- `tracked_tag`
- `latest_version`
- `dist_tags`
- `installed_version`
- `installed`
- `managed_dir`
- `npm_cache_dir`
- `state`

Estados possiveis:

- `not-installed`
- `up-to-date`
- `update-available`

## Configuracao

Variaveis de ambiente aceitas:

- `POWERBI_MCP_PACKAGE`: pacote npm alvo
- `POWERBI_MCP_TAG`: dist-tag acompanhada, por padrao `latest`
- `POWERBI_MCP_DIR`: pasta local de instalacao
- `POWERBI_MCP_NPM_CACHE`: pasta local de cache do npm

Exemplo:

```powershell
$env:POWERBI_MCP_TAG = "latest"
python scripts/powerbi_mcp_manager.py update
```
