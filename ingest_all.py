#!/usr/bin/env python3
"""Unified Ingestion & Analytics Bootstrap Script.

Ingests and pre-analyzes all DAQ CSV recordings, technical knowledge PDFs,
and email archives in a single automated command with incremental caching.

Usage:
    python ingest_all.py
    python ingest_all.py --force
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

# Load environment configuration
load_dotenv(Path(__file__).resolve().parent / ".env")

import api.main as daq_api
from ingestion import knowledge_docs
from knowledge.graph_store import neo4j


def _process_one_condition_worker(cond_id: str, force: bool = False) -> tuple[str, bool, float, int, int]:
    t0 = time.time()
    scope_req = daq_api.AnalyseRequest(condition_id=cond_id)
    if not daq_api.daq_state.conditions:
        dataset_root = daq_api.resolve_daq_dataset_root("dataset/Readngs_DAQ_Data")
        config_path = daq_api.resolve_project_path("config/domain.yaml")
        daq_api._run_daq_ingest(dataset_root, config_path)
    cache_key = daq_api._analysis_cache_key(daq_api.daq_state.dataset_fingerprint, scope_req)
    cache_path = daq_api._analysis_cache_path(cache_key)
    cached = None if force else daq_api._read_cache(cache_path)
    if cached is not None:
        return cond_id, True, time.time() - t0, len(cached.get("windows", [])), len(cached.get("findings", []))

    result, windows, findings, baselines = daq_api._run_analysis_pure(scope_req)
    daq_api._save_analysis_cache_direct(cache_key, result, windows, findings, baselines)
    return cond_id, False, time.time() - t0, len(windows), len(findings)


def run_unified_ingest(
    force: bool = False,
    precompute_analysis: bool = True,
    conditions_filter: list[str] | None = None,
) -> dict:
    start_time = time.time()
    print("=" * 65)
    print("  INSTITUTIONAL MEMORY — UNIFIED INGESTION & BOOTSTRAP")
    print("=" * 65)

    # 1. Ingest Technical Knowledge PDFs
    print("\n[1/4] Ingesting Technical Knowledge Documents (PDFs)...")
    pdf_results = knowledge_docs.ingest_knowledge_docs(daq_api.pipeline)
    ingested_pdf_count = len(pdf_results.get("documents", {}))
    failed_pdf_count = len(pdf_results.get("failed", {}))
    print(f"  ✓ Indexed {ingested_pdf_count} PDF document(s) into vector store & knowledge graph.")
    for doc_name, chunks in pdf_results.get("documents", {}).items():
        print(f"    - {doc_name}: {chunks} chunks")
    if failed_pdf_count > 0:
        for failed_doc, err in pdf_results.get("failed", {}).items():
            print(f"    ! Failed {failed_doc}: {err}")

    # 2. Ingest Machine Operational Emails & Discard Non-Machine
    print("\n[2/4] Ingesting Machine Operational Emails & Discarding Non-Machine...")
    from ingestion import emails
    email_results = emails.ingest_machine_emails(daq_api.pipeline, force=force)
    ingested_email_count = email_results.get("ingested_count", 0)
    discarded_email_count = email_results.get("discarded_count", 0)
    print(f"  ✓ Ingested {ingested_email_count} machine-relevant email(s) into vector store & knowledge graph.")
    print(f"  ✓ Discarded {discarded_email_count} non-machine email(s) from ingestion pipeline.")
    for eml_name, n_chunks in email_results.get("emails", {}).items():
        n_c = n_chunks.get("chunks", 1) if isinstance(n_chunks, dict) else n_chunks
        print(f"    - [ACCEPTED] {eml_name}: {n_c} chunks")

    # 3. Ingest & Profile DAQ Sensor Dataset (CSVs)
    print("\n[3/4] Ingesting & Profiling DAQ Sensor Dataset (CSVs)...")
    conditions_count = 0
    recordings_count = 0
    canonical_count = 0
    try:
        import os
        raw_root = os.environ.get("DAQ_DATASET_ROOT", "dataset/Readngs_DAQ_Data")
        dataset_root = daq_api.resolve_daq_dataset_root(raw_root)
        config_path = daq_api.resolve_project_path(os.environ.get("DAQ_CONFIG_PATH", "config/domain.yaml"))
        daq_api._run_daq_ingest(dataset_root, config_path, force=force)
        conditions_count = len(daq_api.daq_state.conditions)
        recordings_count = len(daq_api.daq_state.recordings)
        canonical_count = len([r for r in daq_api.daq_state.recordings if r.schema_status == "canonical"])
        print(f"  ✓ DAQ Profile Complete: {recordings_count} recordings ({canonical_count} canonical) across {conditions_count} conditions.")
    except Exception as e:
        print(f"  ℹ DAQ CSV dataset not present ({e}).")
        print("  ℹ Running in dataset-free mode: PDF manuals, machine emails, ontology graph, and ML models are fully active.")

    # 4. Pre-compute Baseline Signal Analytics & Findings
    print("\n[4/4] Pre-computing Baseline Signal Analytics...")
    analysed_conditions = 0
    if precompute_analysis and daq_api.daq_state.conditions:
        all_sorted = sorted(daq_api.daq_state.conditions.keys(), key=lambda x: int(x) if x.isdigit() else 999)
        if conditions_filter:
            target_conditions = [c for c in all_sorted if c in conditions_filter]
        else:
            target_conditions = all_sorted

        total_targets = len(target_conditions)

        from concurrent.futures import ProcessPoolExecutor, as_completed
        import os

        # True parallel execution across CPU cores
        max_workers = min(6, os.cpu_count() or 4)
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_process_one_condition_worker, c, force): c for c in target_conditions}
            for idx, future in enumerate(as_completed(futures), start=1):
                cond_id, from_cache, cond_elapsed, n_windows, n_findings = future.result()
                if from_cache:
                    print(f"  [{idx}/{total_targets}] ✓ Condition {cond_id} restored from cache.")
                else:
                    print(f"  [{idx}/{total_targets}] ✓ Condition {cond_id} computed ({cond_elapsed:.1f}s, {n_windows} windows, {n_findings} findings).")
                analysed_conditions += 1

        # Hydrate all cached analyses into active memory and indexes
        daq_api._restore_cached_analyses()
        print(f"  ✓ Pre-warmed {analysed_conditions} condition baselines and anomaly findings in memory & .daq_cache/")
    else:
        print("  ℹ Skipping DAQ signal pre-computation (no raw DAQ CSV recordings mounted).")

    elapsed = time.time() - start_time
    print("\n" + "=" * 65)
    print(f"  UNIFIED BOOTSTRAP COMPLETE in {elapsed:.2f}s!")
    print(f"  • PDFs indexed:       {ingested_pdf_count}")
    print(f"  • Emails indexed:     {ingested_email_count} ({discarded_email_count} discarded non-machine)")
    print(f"  • DAQ Conditions:     {conditions_count}")
    print(f"  • DAQ Recordings:     {recordings_count} ({canonical_count} canonical)")
    print(f"  • Pre-warmed Scopes:  {analysed_conditions}")
    print(f"  • Knowledge Graph:    {len(neo4j.nodes)} nodes, {len(neo4j.edges)} edges")
    print("=" * 65 + "\n")

    return {
        "status": "success",
        "elapsed_seconds": elapsed,
        "pdfs_indexed": ingested_pdf_count,
        "emails_indexed": ingested_email_count,
        "emails_discarded": discarded_email_count,
        "conditions": conditions_count,
        "recordings": recordings_count,
        "canonical_recordings": canonical_count,
        "analysed_conditions": analysed_conditions,
    }


def main():
    parser = argparse.ArgumentParser(description="Ingest all CSVs, PDFs, and pre-compute analysis for all 25 conditions.")
    parser.add_argument("--force", action="store_true", help="Force recomputation ignoring cache.")
    parser.add_argument("--conditions", type=str, default=None, help="Comma-separated list of conditions (e.g. '1,4,7'). Defaults to all 25 conditions.")
    parser.add_argument("--sample", action="store_true", help="Only pre-compute a sample of conditions (1, 2, 4, 7, 12).")
    parser.add_argument("--skip-analysis", action="store_true", help="Skip pre-computing signal analytics.")
    args = parser.parse_args()

    conditions_filter = None
    if args.sample:
        conditions_filter = ["1", "2", "4", "7", "12"]
    elif args.conditions:
        conditions_filter = [c.strip() for c in args.conditions.split(",") if c.strip()]

    try:
        run_unified_ingest(
            force=args.force,
            precompute_analysis=not args.skip_analysis,
            conditions_filter=conditions_filter,
        )
    except Exception as e:
        print(f"\n[ERROR] Bootstrap failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
