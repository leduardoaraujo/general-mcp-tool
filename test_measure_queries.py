#!/usr/bin/env python3
"""
Quick test script for Power BI measure value query improvements.
Run this to validate the new functionality before full integration.
"""

import sys
sys.path.insert(0, '/workspace/src')

from mcp_orchestrator.application.power_bi_measures import (
    find_matching_measure,
    extract_date_filter_from_query,
    MeasureContext,
)
from mcp_orchestrator.application.dax_executor import DaxQueryGenerator
from mcp_orchestrator.application.intake import HeuristicRequestUnderstandingService
from mcp_orchestrator.domain.models import UserRequest


def test_measure_detection():
    """Test measure matching from user queries."""
    print("=" * 60)
    print("TEST 1: Measure Detection")
    print("=" * 60)
    
    test_cases = [
        "Quantos Movimentações eu tive em fevereiro de 2026?",
        "Qual o total de PJs Ativos?",
        "Qual foi minha taxa de distrato em Q2 2026?",
        "Contratos no período de março",
    ]
    
    for query in test_cases:
        measure = find_matching_measure(query)
        if measure:
            print(f"✅ Query: {query}")
            print(f"   → Measure: {measure.display_name}")
            print(f"   → Internal: {measure.internal_name}")
        else:
            print(f"❌ Query: {query}")
            print(f"   → No measure found")
        print()


def test_date_extraction():
    """Test date filter extraction from queries."""
    print("=" * 60)
    print("TEST 2: Date Filter Extraction")
    print("=" * 60)
    
    test_cases = [
        "Quantos Movimentações eu tive em fevereiro de 2026?",
        "Qual foi o total em janeiro?",
        "Saldo de Q2 2026",
        "Contratos em março de 2025",
    ]
    
    for query in test_cases:
        date_filter = extract_date_filter_from_query(query)
        if date_filter:
            print(f"✅ Query: {query}")
            print(f"   → Date Filter: {date_filter}")
        else:
            print(f"⚠️  Query: {query}")
            print(f"   → No date found (might be OK)")
        print()


def test_measure_context():
    """Test MeasureContext creation."""
    print("=" * 60)
    print("TEST 3: MeasureContext Creation")
    print("=" * 60)
    
    query = "Quantos Movimentações eu tive em fevereiro de 2026?"
    measure = find_matching_measure(query)
    date_filter = extract_date_filter_from_query(query)
    
    if measure:
        context = MeasureContext(measure, date_filter)
        print(f"✅ Context created successfully")
        print(f"   → {context.to_dict()}")
    else:
        print(f"❌ Could not create context - measure not found")
    print()


def test_dax_generation():
    """Test DAX query generation."""
    print("=" * 60)
    print("TEST 4: DAX Query Generation")
    print("=" * 60)
    
    # Test Case 1: With date filter
    query1 = "Quantos Movimentações eu tive em fevereiro de 2026?"
    measure1 = find_matching_measure(query1)
    date_filter1 = extract_date_filter_from_query(query1)
    
    if measure1:
        context1 = MeasureContext(measure1, date_filter1)
        dax1 = DaxQueryGenerator.generate_query(context1)
        print(f"✅ Test Case 1: With date filter")
        print(f"   Query: {query1}")
        print(f"   DAX:\n{dax1}\n")
    
    # Test Case 2: Without date filter
    query2 = "Qual o total de PJs Ativos?"
    measure2 = find_matching_measure(query2)
    date_filter2 = extract_date_filter_from_query(query2)
    
    if measure2:
        context2 = MeasureContext(measure2, date_filter2)
        dax2 = DaxQueryGenerator.generate_query(context2)
        print(f"✅ Test Case 2: Without date filter")
        print(f"   Query: {query2}")
        print(f"   DAX:\n{dax2}\n")
    
    # Test Case 3: Simple DAX
    print(f"✅ Test Case 3: Simple DAX generation")
    simple_dax = DaxQueryGenerator.generate_simple_dax_query(
        "[Movimentacao Periodo]",
        year=2026,
        month=2
    )
    print(f"   DAX:\n{simple_dax}\n")


def test_request_understanding():
    """Test enhanced request understanding service."""
    print("=" * 60)
    print("TEST 5: Request Understanding Service")
    print("=" * 60)
    
    service = HeuristicRequestUnderstandingService()
    
    test_cases = [
        "Quantos Movimentações eu tive em fevereiro de 2026?",
        "Liste as medidas disponíveis",
        "Qual o DAX de Movimentacao Periodo?",
        "Qual o total de PJs Ativos?",
    ]
    
    for query in test_cases:
        request = UserRequest(message=query)
        understanding = service.understand(request)
        
        print(f"📝 Query: {query}")
        print(f"   Task Type: {understanding.task_type.value}")
        print(f"   Action: {understanding.requested_action.value}")
        print(f"   Confidence: {understanding.confidence}")
        print()


def main():
    """Run all tests."""
    print("\n")
    print("🧪 POWER BI MEASURE VALUE QUERY - TEST SUITE")
    print("=" * 60)
    print()
    
    try:
        test_measure_detection()
        test_date_extraction()
        test_measure_context()
        test_dax_generation()
        test_request_understanding()
        
        print()
        print("=" * 60)
        print("✅ ALL TESTS COMPLETED")
        print("=" * 60)
        print()
        print("Next Steps:")
        print("1. Review test output above")
        print("2. Verify measure detection works for your domain")
        print("3. Check DAX generation produces valid syntax")
        print("4. Implement routing handler (see INTEGRATION_CHECKLIST.md)")
        print()
        
    except Exception as e:
        print()
        print("=" * 60)
        print(f"❌ ERROR: {str(e)}")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
