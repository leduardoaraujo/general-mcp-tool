# Power BI Semantic Model Inspection

Rule ID: power_bi.semantic_model_inspection
Domain: power_bi
Tags: power_bi, semantic_model, modelo, medidas, tabelas, relatorio, dax, measures, business_rules
Applies To: Power BI Desktop semantic model inspection, table listing, measure listing, DAX preview, modelo semantico, medidas e tabelas.
Business Definition: Governed KPI answers should prefer semantic model measures when the user asks about metrics, measures, medidas, dashboards, relatorios, or business KPIs.
Data Sources: Open Power BI Desktop model discovered through the Power BI Modeling MCP local instance connection.
SQL/DAX Guidance: Use metadata inspection, table listing, measure listing, and DAX preview before proposing model changes. Do not refresh or mutate the model in the MVP.
Validation Notes: Confirm the connected local instance matches the intended report before using model metadata in the final answer.
Owner: Analytics Engineering
Last Reviewed: 2026-05-05

Use this rule for safe semantic model analysis through the MCP orchestrator.
