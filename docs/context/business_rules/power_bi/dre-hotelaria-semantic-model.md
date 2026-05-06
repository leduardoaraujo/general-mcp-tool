# Base Documental - Modelo Semântico DRE - Hotelaria

Data de extração: 2026-05-06  
Fonte: MCP Power BI (`mcp_servers.powerbi`) conectado ao relatório aberto `DRE - Hotelaria`

## 1) Resumo de Negócio (Hotelaria)

O modelo foi estruturado para monitorar performance econômico-financeira e operação hoteleira em uma mesma camada semântica.

Principais perguntas de negócio suportadas:
- Como está o resultado da DRE no período (Receita Líquida, Custos, EBITDA, Lucro Líquido)?
- Como os indicadores evoluem contra o ano anterior (LY/YoY)?
- Como está a produtividade por disponibilidade de quartos (GOPPAR/GOPPOR)?
- Como está a dinâmica comercial e operacional de reservas (receita, diária média, ocupação, TRevPAR)?
- Como a ocupação e disponibilidade de UHs variam no tempo e no acumulado?

Domínios de indicadores identificados:
- DRE e margens: Receita Líquida, Custos, EBITDA, Lucro Líquido, percentuais e subtotais.
- Receita e rentabilidade operacional: GOP, GOPPAR/GOPPOR, TRevPAR, diária média.
- Reservas e demanda: quantidade de reservas, diárias, hóspedes, composição por perfil (cotista/pool/convidado), acumulados.
- Ocupação e capacidade: ocupação %, UHs disponíveis, UHs bloqueados, ocupação acumulada e comparação ano anterior.

## 2) Resumo Técnico do Modelo

Estatísticas gerais do modelo (`Model`):
- Modo: `Import`
- Cultura: `pt-BR`
- Compatibilidade: `1601`
- Tabelas: `28`
- Medidas: `196`
- Colunas: `325`
- Relacionamentos: `21`

Tabelas centrais:
- `Medidas` (81 medidas): camada principal de DRE, margens e indicadores consolidados.
- `Reservas` (98 medidas): camada operacional/comercial de hotelaria.
- `UH` (17 medidas): capacidade e ocupação de unidades habitacionais.
- `movimentacao_contabil`: base contábil para cálculos da DRE/GOP.
- `Estrutura_DRE`: estrutura de linhas/ordem da DRE usada nos cálculos por subtotal.
- `Calendario` e `dCalendario`: suporte temporal para análises por período e YoY.

Arquitetura de cálculo observada:
- Medidas DRE em `Medidas` usando `CALCULATE` + filtros em `Estrutura_DRE[Ordem]`.
- Parte relevante da hotelaria operacional usa `EXTERNALMEASURE(...)`, consumindo medidas externas de modelos/fonte analítica:
  - `DirectQuery para AS – GFP - Hotelaria`
  - `DirectQuery para AS – GFP - Hotelaria 2`
  - `DirectQuery para AS – GFP - Hotelaria 3`

Implicação técnica:
- O relatório local consolida métrica própria (DRE) + métricas externas (operação hoteleira), reduzindo duplicação de regra no PBIX e centralizando lógica de origem.

## 3) Medidas-Chave (negócio + técnica)

### 3.1 Núcleo DRE

1. Receita Líquida (`Medidas[Receita Liquida]`)
```DAX
CALCULATE(
    [DRE Subtotal],
    ALL(Estrutura_DRE),
    Estrutura_DRE[Ordem] = 5
)
```
Uso: valor consolidado de receita líquida na estrutura DRE.

2. Custos (`Medidas[Custos]`)
```DAX
CALCULATE(
    [DRE Analitico],
    Estrutura_DRE[Ordem] = 6
)
```
Uso: custos vinculados à linha estrutural da DRE.

3. EBITDA (`Medidas[Ebtida]`)
```DAX
CALCULATE(
    [DRE Subtotal],
    Estrutura_DRE[Ordem] = 25
)
```
Uso: resultado operacional antes de juros, impostos, depreciação e amortização.

4. Lucro Líquido (`Medidas[Lucro Líquido]`)
```DAX
CALCULATE(
    [DRE Subtotal],
    Estrutura_DRE[Ordem] = 32
)
```
Uso: resultado final após despesas e tributos.

### 3.2 Rentabilidade Hotelaria

5. GOP (`Medidas[GOP]`)
```DAX
CALCULATE(
    SUM(movimentacao_contabil[valor]),
    movimentacao_contabil[dPlanoContas.GOP] = "GOP"
)
```
Uso: lucro operacional bruto para análise de eficiência da operação.

6. GOPPAR (`Medidas[GOPPAR]`)
```DAX
DIVIDE(
    [GOP],
    [Qtd Aptos Disponíveis Ajustado],
    BLANK()
)
```
Uso: lucro operacional por quarto disponível.

### 3.3 Operação Comercial e Ocupação

7. Receita de Hospedagem (`Reservas[Vlr Receita]`)
```DAX
EXTERNALMEASURE("Vlr Receita", DOUBLE, "DirectQuery para AS – GFP - Hotelaria")
```
Uso: valor de receita operacional de reservas vindo de camada externa.

8. Diária Média (`Reservas[Vlr Diária Média]`)
```DAX
EXTERNALMEASURE("Vlr Diária Média", DOUBLE, "DirectQuery para AS – GFP - Hotelaria")
```
Uso: ticket médio diário de hospedagem.

9. TRevPAR (`Reservas[Vlr TRevPAR]`)
```DAX
EXTERNALMEASURE("Vlr TRevPAR", DOUBLE, "DirectQuery para AS – GFP - Hotelaria")
```
Uso: receita total por quarto disponível.

10. Ocupação % (`UH[% Ocupação]`)
```DAX
EXTERNALMEASURE("% Ocupação", DOUBLE, "DirectQuery para AS – GFP - Hotelaria 2")
```
Uso: taxa de ocupação da capacidade hoteleira.

11. Aptos Disponíveis (`UH[Qtd Aptos Disponíveis]`)
```DAX
EXTERNALMEASURE("Qtd Aptos Disponíveis", INTEGER, "DirectQuery para AS – GFP - Hotelaria 2")
```
Uso: base de capacidade para indicadores per-room.

12. Ocupação em Volume (`Reservas[Qtd Ocupação]`)
```DAX
EXTERNALMEASURE("Qtd Ocupação", INTEGER, "DirectQuery para AS – GFP - Hotelaria")
```
Uso: quantidade ocupada para leitura operacional diária/período.

## 4) Catálogo por Domínio (base inicial)

- DRE e Margens (`Medidas`): 81 medidas
  - Ex.: `Receita Liquida`, `Custos`, `Ebtida`, `Lucro Líquido`, `% CMV`, `% MB`, `% EBITDA`, `% LL`, variações LY/YoY.
- Reservas e Receita (`Reservas`): 98 medidas
  - Ex.: `Vlr Receita`, `Vlr Diária Média`, `Vlr TRevPAR`, `Qtd Reservas`, `Qtd Diárias Período`, acumulados e comparativos AA/YoY.
- Capacidade/Ocupação (`UH`): 17 medidas
  - Ex.: `% Ocupação`, `Qtd Aptos Disponíveis`, `% Ocupação Acumulada`, `% Ocupação Pool`.

## 5) Recomendações para evolução da documentação

- Criar dicionário funcional por medida crítica (definição de negócio, fórmula, granularidade, filtros esperados).
- Identificar owner por domínio (`Financeiro DRE`, `Receitas/Reservas`, `Operação UH`).
- Registrar dependências externas (`EXTERNALMEASURE`) com SLA e contato de sustentação.
- Formalizar regra de leitura temporal (Mês, Acumulado, LY, YoY) para evitar interpretações divergentes entre áreas.
