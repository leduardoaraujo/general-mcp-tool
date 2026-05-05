"""Power BI measure mapping and NLP matching for sales domain."""

from dataclasses import dataclass
from typing import Any


@dataclass
class MeasureDefinition:
    """Semantic definition of a Power BI measure."""
    internal_name: str
    display_name: str
    aliases: list[str]
    description: str
    requires_date_filter: bool = True
    temporal_grain: str | None = None  # "month", "quarter", "year"


# Sales domain measures mapping
SALES_MEASURES = {
    "Movimentacao Periodo": MeasureDefinition(
        internal_name="Movimentacao Periodo",
        display_name="Movimentação no Período",
        aliases=["movimentacao", "movimentações", "movimento", "movimentos", "trafego"],
        description="Total de movimentações de PJs no período",
        requires_date_filter=True,
        temporal_grain="month",
    ),
    "Contratos Periodo": MeasureDefinition(
        internal_name="Contratos Periodo",
        display_name="Contratos no Período",
        aliases=["contratos", "contrato", "novos contratos", "novas contratacoes"],
        description="Total de novos contratos no período",
        requires_date_filter=True,
        temporal_grain="month",
    ),
    "Distratos Periodo": MeasureDefinition(
        internal_name="Distratos Periodo",
        display_name="Distratos no Período",
        aliases=["distratos", "distrato", "cancelamentos", "cancelamento", "saidas"],
        description="Total de distratos/cancelamentos no período",
        requires_date_filter=True,
        temporal_grain="month",
    ),
    "Recontratacoes Periodo": MeasureDefinition(
        internal_name="Recontratacoes Periodo",
        display_name="Recontratações no Período",
        aliases=["recontratacoes", "recontratacao", "renovacoes", "renovacao"],
        description="Total de recontratações no período",
        requires_date_filter=True,
        temporal_grain="month",
    ),
    "Saldo Liquido Periodo": MeasureDefinition(
        internal_name="Saldo Liquido Periodo",
        display_name="Saldo Líquido no Período",
        aliases=["saldo liquido", "saldo", "resultado liquido", "resultado"],
        description="Saldo líquido (contratos - distratos) no período",
        requires_date_filter=True,
        temporal_grain="month",
    ),
    "PJs Ativos": MeasureDefinition(
        internal_name="PJs Ativos",
        display_name="PJs Ativos",
        aliases=["pjs ativos", "ativos", "pjs ativas"],
        description="Total de PJs ativas",
        requires_date_filter=False,
        temporal_grain=None,
    ),
    "PJs Inativos": MeasureDefinition(
        internal_name="PJs Inativos",
        display_name="PJs Inativos",
        aliases=["pjs inativos", "inativos", "pjs inativas"],
        description="Total de PJs inativas",
        requires_date_filter=False,
        temporal_grain=None,
    ),
    "% PJs Ativos": MeasureDefinition(
        internal_name="% PJs Ativos",
        display_name="Percentual PJs Ativos",
        aliases=["%", "percentual ativos", "taxa ativos"],
        description="Percentual de PJs ativas",
        requires_date_filter=False,
        temporal_grain=None,
    ),
}


def find_matching_measure(query: str) -> MeasureDefinition | None:
    """
    Find the most relevant measure for a user query using simple NLP.
    Returns the measure definition if found, None otherwise.
    """
    normalized_query = query.lower().strip()
    
    # Direct exact match first
    for measure_def in SALES_MEASURES.values():
        if normalized_query == measure_def.internal_name.lower():
            return measure_def
    
    # Alias match (greedy - first alias match wins)
    for measure_def in SALES_MEASURES.values():
        for alias in measure_def.aliases:
            if alias.lower() in normalized_query:
                return measure_def
    
    return None


def extract_date_filter_from_query(query: str) -> dict[str, Any] | None:
    """
    Extract date information from user query.
    Returns dict with month, quarter, year info or None if no date found.
    
    Examples:
        "fevereiro de 2026" -> {"month": 2, "year": 2026}
        "janeiro" -> {"month": 1}
        "Q1 2026" -> {"quarter": 1, "year": 2026}
        "2026" -> {"year": 2026}
    """
    normalized = query.lower()
    
    # Month patterns
    months = {
        "janeiro": 1, "jan": 1,
        "fevereiro": 2, "fev": 2,
        "março": 3, "mar": 3,
        "abril": 4, "abr": 4,
        "maio": 5,
        "junho": 6, "jun": 6,
        "julho": 7, "jul": 7,
        "agosto": 8, "ago": 8,
        "setembro": 9, "set": 9,
        "outubro": 10, "out": 10,
        "novembro": 11, "nov": 11,
        "dezembro": 12, "dez": 12,
    }
    
    result: dict[str, Any] = {}
    
    # Look for month
    for month_name, month_num in months.items():
        if month_name in normalized:
            result["month"] = month_num
            break
    
    # Look for quarter
    if "q1" in normalized or "q 1" in normalized or "primeiro trimestre" in normalized:
        result["quarter"] = 1
    elif "q2" in normalized or "q 2" in normalized or "segundo trimestre" in normalized:
        result["quarter"] = 2
    elif "q3" in normalized or "q 3" in normalized or "terceiro trimestre" in normalized:
        result["quarter"] = 3
    elif "q4" in normalized or "q 4" in normalized or "quarto trimestre" in normalized:
        result["quarter"] = 4
    
    # Look for year (4-digit number)
    import re
    year_match = re.search(r'\b(20\d{2}|19\d{2})\b', query)
    if year_match:
        result["year"] = int(year_match.group(1))
    
    return result if result else None


class MeasureContext:
    """Context object for measure query execution."""
    def __init__(
        self,
        measure: MeasureDefinition,
        date_filter: dict[str, Any] | None = None,
    ):
        self.measure = measure
        self.date_filter = date_filter or {}
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "measure_name": self.measure.internal_name,
            "display_name": self.measure.display_name,
            "description": self.measure.description,
            "date_filter": self.date_filter,
            "requires_date_filter": self.measure.requires_date_filter,
        }
