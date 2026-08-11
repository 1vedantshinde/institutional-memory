#!/usr/bin/env python3
"""Verification script for Step 1 — The Domain Config & Plugin Registry.

Demonstrates parsing, chunking, validation, and domain-aware prompt building.
"""

import sys
import traceback
from core.config import load_domain_config, DOMAIN
from core.schema import Node, Edge, UnifiedDocument
from core.registry import PARSER_REGISTRY, register_parser, BaseParser

# Import parsers to trigger registration decorators
import ingestion.parsers
import retrieval.embedder
import retrieval.vector_store
from ingestion.pipeline import IngestionPipeline
from llm.orchestrator import RAGOrchestrator

@register_parser("py")
class PythonParser(BaseParser):
    def parse(self, filename: str, content_bytes: bytes, metadata = None) -> UnifiedDocument:
        content = content_bytes.decode("utf-8", errors="ignore")
        return UnifiedDocument(
            doc_id="code_test_uuid",
            modality="code",
            source_path=filename,
            raw_content=content,
            metadata={"language": "python"}
        )

def print_separator(title: str):
    print("\n" + "=" * 60)
    print(f" {title} ")
    print("=" * 60)

def run_test():
    print_separator("1. ACTIVE CONFIGURATION")
    print(f"Active Domain Name: {DOMAIN.domain_name}")
    print(f"Allowed Entity Types: {DOMAIN.entity_types}")
    print(f"Allowed Relation Types: {DOMAIN.relation_types}")
    print("Glossary Dictionary:")
    for item in DOMAIN.glossary:
        print(f"  - {item.term}: {item.meaning}")

    print_separator("2. REGISTERED PLUGINS")
    print(f"Parsers online:      {list(PARSER_REGISTRY.keys())}")
    
    # Initialize pipeline
    pipeline = IngestionPipeline(
        embedder_key="mock",
        vector_store_key="in_memory",
        graph_store_key="in_memory"
    )

    print_separator("3. INGESTING HETEROGENEOUS DATA FORMATS")
    
    # A. PDF Ingestion
    pdf_bytes = b"SOP-402: Emergency Shutdown Procedure. Keep valves closed."
    print("Ingesting PDF...")
    pdf_chunks = pipeline.ingest_file(
        filename="shutdown_sop.pdf",
        content_bytes=pdf_bytes
    )
    print(f"--> Formatted chunk preview: '{pdf_chunks[0].text}'\n")

    # B. CAD/DXF Ingestion
    # Simulated ASCII DXF representation with text entities:
    # 0 -> TEXT (Entity Group Header), 1 -> Pump-101 (Text value), 8 -> Layer_0
    dxf_ascii = b"0\nSECTION\n2\nENTITIES\n0\nTEXT\n1\nPump-101\n8\nLayer_0\n0\nINSERT\n2\nValves-Block\n10\n100.0\n20\n200.0\n0\nENDSEC\n"
    print("Ingesting CAD Drawings (DXF simulation)...")
    cad_chunks = pipeline.ingest_file(
        filename="refinery_layout.dxf",
        content_bytes=dxf_ascii
    )
    print(f"--> Formatted chunk preview: '{cad_chunks[0].text}'\n")

    # C. Email Ingestion
    # Simulated simple raw email:
    email_raw = (
        b"From: maintenance@plant.com\n"
        b"To: safety@plant.com\n"
        b"Subject: Pump-101 failure and Incident report\n"
        b"Date: Mon, 10 Aug 2026 10:00:00 -0500\n"
        b"\n"
        b"Pump-101 failed verification tests during standard P&ID check. "
        b"Suggest checking SOP-402 checklist immediately."
    )
    print("Ingesting Email Archives...")
    email_chunks = pipeline.ingest_file(
        filename="incident_report.eml",
        content_bytes=email_raw
    )
    print(f"--> Formatted chunk preview: '{email_chunks[0].text}'\n")

    # D. Python Code Ingestion (Strategy Override Test)
    code_bytes = b"def calculate_total():\n    return sum(items)\n\ndef format_output(val):\n    return str(val)"
    print("Ingesting Python Code (custom chunk strategy override)...")
    code_chunks = pipeline.ingest_file(
        filename="utils.py",
        content_bytes=code_bytes
    )
    print(f"Generated Chunks: {len(code_chunks)}")
    for j, c in enumerate(code_chunks):
        print(f"  * Chunk {j}: '{c.text}' (strategy: {c.metadata.get('strategy')})")
    print()

    print_separator("4. DYNAMIC ONTOLOGY SCHEMA VALIDATION")
    
    # Prepare valid graph instances complying with configured types
    valid_nodes = [
        {"name": "Pump-101", "type": "Equipment", "properties": {"serial": "1122AA"}},
        {"name": "SOP-402", "type": "Procedure", "properties": {"revision": 4}},
        {"name": "Incident-9", "type": "Incident", "properties": {"severity": "High"}}
    ]
    valid_edges = [
        {"source_id": "Pump-101", "target_id": "SOP-402", "type": "MAINTAINED_BY"},
        {"source_id": "Incident-9", "target_id": "Pump-101", "type": "CAUSED_BY"}
    ]
    
    print("Injecting valid nodes and relationships...")
    pipeline.ingest_graph_elements(valid_nodes, valid_edges)
    
    # Try injecting invalid entities to verify validation guardrails
    invalid_nodes = [
        {"name": "Safety-Zone", "type": "UnknownRoleType"} # 'UnknownRoleType' is not in domain.yaml
    ]
    print("\nAttempting invalid node type ingestion (should fail)...")
    try:
        pipeline.ingest_graph_elements(invalid_nodes, [])
        print("ERROR: Validation failed to detect invalid type!")
        sys.exit(1)
    except ValueError as e:
        print(f"SUCCESS: Rejected invalid node as expected. Message: {e}")

    invalid_edges = [
        {"source_id": "Pump-101", "target_id": "SOP-402", "type": "LOVES"} # 'LOVES' is not in domain.yaml
    ]
    print("\nAttempting invalid relation type ingestion (should fail)...")
    try:
        pipeline.ingest_graph_elements([], invalid_edges)
        print("ERROR: Validation failed to detect invalid relationship type!")
        sys.exit(1)
    except ValueError as e:
        print(f"SUCCESS: Rejected invalid edge as expected. Message: {e}")

    print_separator("5. END-TO-END RAG ORCHESTRATION WITH GLOSSARY MATCHER")
    
    # Instantiate orchestrator using the already populated in-memory stores
    orchestrator = RAGOrchestrator(
        llm_key="mock",
        embedder_key="mock",
        vector_store_key="in_memory"
    )
    # Direct reuse of the pipeline's memory collections (since they share registry instance type memory)
    # To ensure chunks we loaded exist in search, we copy pipeline stores references
    orchestrator.vector_store = pipeline.vector_store
    
    # The query below mentions P&ID, which is in our domain.yaml glossary.
    # The glossary matcher should identify it and auto-expand definitions.
    user_query = "What happens if Pump-101 fails during a P&ID review?"
    print(f"Querying: '{user_query}'")
    
    response = orchestrator.query(user_query, limit=2)
    print("\nSystem Prompt Used:")
    print("-" * 30)
    print(response["system_prompt"])
    print("-" * 30)
    
    print("\nGenerated Answer:")
    print(response["answer"])
    
    print("\nReturned Grounded Citations:")
    for citation in response["citations"]:
        print(f"  * [{citation['modality']}] {citation['source_path']}, Chunk {citation['chunk_index']}")
        print(f"    Snippet: \"{citation['snippet']}\"")

    print("\n" + "=" * 60)
    print(" ALL STEP 2 & 3 TESTS COMPLETED SUCCESSFULLY! ")
    print("=" * 60)

if __name__ == "__main__":
    try:
        run_test()
    except Exception as e:
        print(f"\nTest execution failed:")
        traceback.print_exc()
        sys.exit(1)
