"""Machine Email Ingestion & Domain Relevance Filter.

Ingests machine operational, maintenance, experimental, and calibration emails
into the knowledge graph and vector store while strictly filtering out and
discarding any non-machine emails (e.g. general corporate talk, energy trading,
payroll, personal banter).
"""

from __future__ import annotations

import email
import email.policy
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from core.schema import Chunk, UnifiedDocument, make_doc_id
from knowledge.graph_store import neo4j
from retrieval.retriever import bm25_index

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_EMAILS_ROOT = PROJECT_ROOT / "knowledge_docs" / "emails"
EMAILDATA_ROOT = PROJECT_ROOT / "emaildata"

# Comprehensive domain keywords & patterns for CNC Milling Machine Relevance
MACHINE_DOMAIN_PATTERNS: List[re.Pattern] = [
    # Machine Components & Equipment
    re.compile(r"\b(cnc|milling(?:\s+machine)?|machining(?:\s+center)?|deckel\s*maho|spindle|tool\s*holder|cutter|face\s*mill(?:ing)?|end\s*mill|carbide\s*insert|dynamometer|kistler|load\s*cell|accelerometer|bearing|3-axis|feed\s*motor)\b", re.IGNORECASE),
    # Sensor Channels & DAQ
    re.compile(r"\b(vib_spindle|vib_table|x_load_cell|y_load_cell|z_load_cell|motor\s*current|spindle\s*current|current\s*draw|daq|sampling\s*rate|10000\s*hz|10\s*khz|analog\s*channel|raw\s*voltage)\b", re.IGNORECASE),
    # Process Parameters & Settings
    re.compile(r"\b(spindle\s*speed|feed\s*rate|depth\s*of\s*cut|cutting\s*speed|latin\s*square|orthogonal\s*array|condition\s*\d+|s\s*800|s\s*1040|s\s*1280|s\s*1600|f\s*20|f\s*35|f\s*50|f\s*65|d\s*0\.1|d\s*0\.25|d\s*0\.35|d\s*0\.45|d\s*0\.6)\b", re.IGNORECASE),
    # Signal Features & Anomalies
    re.compile(r"\b(vibration|chatter|kurtosis|crest\s*factor|rms|skewness|spectral\s*band|spectral\s*centroid|mahalanobis|anomaly|anomalies|baseline|harmonic|zero-offset|zero-drift|thermal\s*drift)\b", re.IGNORECASE),
    # Tool Wear & Quality Policies
    re.compile(r"\b(tool\s*wear|flank\s*wear|vb\b|crater\s*wear|tool\s*life|insert\s*wear|iso\s*3685|quarantine|canonical\s*schema|column_count_mismatch|null_bytes|missing_header|recording\s*\d+)\b", re.IGNORECASE),
    # Maintenance & Calibration Operations
    re.compile(r"\b(preventive\s*maintenance|bearing\s*lubrication|spindle\s*grease|piezoelectric|calibration|zero-drift|optical\s*microscope|workpiece|aisi\s*1045|mondragon)\b", re.IGNORECASE),
]

# Seed concept and entity mapping per machine email file
CONCEPTS_PER_EMAIL: Dict[str, Dict[str, Any]] = {
    "spindle_vibration_alert_cond4.eml": {
        "sender": "Marcus Vance",
        "sender_email": "marcus.vance@machining-lab.org",
        "recipients": ["Dr. Elena Rodriguez", "Maintenance Team"],
        "subject": "High Spindle Vibration Alert during Condition 4 Runs (S800 F35 D0.25)",
        "condition_id": "4",
        "components": ["Spindle", "Vib_Spindle", "Accelerometer"],
        "faults": ["High Spindle Vibration", "Spindle Bearing Runout"],
        "concepts": ["kurtosis", "crest factor", "mahalanobis", "baseline deviation", "condition 4"],
    },
    "tool_wear_inspection_cond12.eml": {
        "sender": "David Chen",
        "sender_email": "david.chen@machining-lab.org",
        "recipients": ["Sarah Jenkins", "Marcus Vance"],
        "subject": "Severe Flank Wear & Chatter Observed on Condition 12 Cutters",
        "condition_id": "12",
        "components": ["Face Milling Cutter", "Z_Load_Cell", "Vib_Table", "Carbide Insert"],
        "faults": ["Severe Flank Wear", "Milling Chatter"],
        "concepts": ["flank wear", "tool wear", "iso 3685", "spectral band energy", "condition 12"],
    },
    "kistler_dynamometer_calibration.eml": {
        "sender": "Alex Rivera",
        "sender_email": "alex.rivera@machining-lab.org",
        "recipients": ["DAQ Team", "Marcus Vance"],
        "subject": "Calibration & Zero-Drift Verification for Kistler 3-Axis Load Cells",
        "condition_id": None,
        "components": ["Kistler Dynamometer", "X_Load_Cell", "Y_Load_Cell", "Z_Load_Cell"],
        "faults": [],
        "concepts": ["sampling rate", "calibration", "zero-offset drift", "raw voltage", "10000 hz"],
    },
    "quarantine_corrupt_csv_incident.eml": {
        "sender": "Rachel Torres",
        "sender_email": "rachel.torres@machining-lab.org",
        "recipients": ["Marcus Vance", "DAQ Team"],
        "subject": "Quarantine Notice: Corrupt CSV File Formats in Raw DAQ Batches",
        "condition_id": None,
        "components": ["DAQ Recording Files"],
        "faults": ["Corrupt CSV Files", "Missing Columns", "Null Bytes"],
        "concepts": ["quarantine", "canonical schema", "column_count_mismatch", "null bytes"],
    },
    "spindle_bearing_lubrication_log.eml": {
        "sender": "Tom Bradley",
        "sender_email": "tom.bradley@facility-engineering.org",
        "recipients": ["Marcus Vance", "David Chen"],
        "subject": "Completed Spindle Bearing Lubrication & Thermal Check",
        "condition_id": None,
        "components": ["Spindle", "Spindle Hybrid Bearing", "Motor Current"],
        "faults": [],
        "concepts": ["preventive maintenance", "bearing lubrication", "current draw", "thermal check"],
    },
    "cutting_conditions_latin_square.eml": {
        "sender": "Dr. Elena Rodriguez",
        "sender_email": "dr.elena.rodriguez@mondragon-machining.org",
        "recipients": ["DAQ Team", "David Chen", "Marcus Vance"],
        "subject": "Experimental Matrix for 25 Milling Process Conditions (S, F, D)",
        "condition_id": "all",
        "components": ["Deckel Maho CNC", "Face Milling Cutter", "AISI 1045 Workpiece"],
        "faults": [],
        "concepts": ["latin-square design", "spindle speed", "feed rate", "depth of cut", "25 conditions"],
    },
}

# Tracking state
_ingested_emails: Dict[str, Dict[str, Any]] = {}
_discarded_emails: Dict[str, str] = {}


def is_machine_relevant_email(content: str, subject: str = "", sender: str = "") -> Tuple[bool, str]:
    """Evaluates whether an email is genuinely relevant to the CNC milling machine domain.
    
    Returns (is_relevant: bool, reason: str).
    """
    full_text = f"Subject: {subject}\nSender: {sender}\n\n{content}"
    
    # Check for domain pattern matches
    matches = []
    for pattern in MACHINE_DOMAIN_PATTERNS:
        found = pattern.findall(full_text)
        if found:
            matches.extend(found)
            
    if len(matches) >= 2:
        return True, f"matched_{len(matches)}_machine_terms"
    if len(matches) == 1:
        # Require strong machine term if only single match
        single_term = matches[0].lower()
        if single_term in {"cnc", "spindle", "vib_spindle", "vib_table", "x_load_cell", "y_load_cell", "z_load_cell", "kistler", "dynamometer", "flank wear", "tool wear", "latin square"}:
            return True, f"matched_primary_machine_term:{single_term}"

    return False, "discarded_not_machine_related"


def parse_raw_email_file(file_path: Path) -> Tuple[str, str, str, str, str]:
    """Parse standard .eml, .msg, or maildir text file into (sender, recipients, subject, date, body)."""
    content_bytes = file_path.read_bytes()
    try:
        msg = email.message_from_bytes(content_bytes, policy=email.policy.default)
        sender = str(msg.get("From", "Unknown"))
        recipients = str(msg.get("To", "Unknown"))
        subject = str(msg.get("Subject", "No Subject"))
        date_str = str(msg.get("Date", ""))
        
        body_parts = []
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disp = str(part.get("Content-Disposition") or "")
                if content_type == "text/plain" and "attachment" not in content_disp:
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body_parts.append(payload.decode(charset, errors="ignore"))
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                body_parts.append(payload.decode(charset, errors="ignore"))
                
        body = "\n".join(body_parts).strip()
        if not body:
            # Fallback to plain text decoding of file
            body = content_bytes.decode("utf-8", errors="ignore")
    except Exception:
        body = content_bytes.decode("utf-8", errors="ignore")
        sender = "Unknown"
        recipients = "Unknown"
        subject = file_path.name
        date_str = ""

    return sender, recipients, subject, date_str, body


def ingest_machine_emails(
    pipeline: Any,
    email_roots: Optional[List[Path | str]] = None,
    force: bool = False,
    max_scan_files: int = 500,
) -> Dict[str, Any]:
    """Ingests and links all machine-relevant emails while discarding non-machine communications.
    
    1. Discovers emails in knowledge_docs/emails/ and optional email archives.
    2. Runs the strict Machine Relevance Filter.
    3. Discards non-machine emails with logged reason.
    4. Chunks, embeds, and indexes accepted machine emails into vector store.
    5. Builds Email, Person, Component, Fault, Condition nodes and relationships in Neo4j.
    """
    global _ingested_emails, _discarded_emails
    
    if not force and _ingested_emails and len(_ingested_emails) >= 6:
        return {
            "ingested_count": len(_ingested_emails),
            "discarded_count": len(_discarded_emails),
            "emails": dict(_ingested_emails),
            "discarded": dict(_discarded_emails),
        }

    if email_roots is None:
        email_roots = [KNOWLEDGE_EMAILS_ROOT, EMAILDATA_ROOT]

    discovered_files: List[Path] = []
    for root in email_roots:
        p = Path(root)
        if not p.is_dir():
            continue
        # Check .eml, .msg, .txt or maildir leaf files
        for ext in ("*.eml", "*.msg", "*.txt"):
            discovered_files.extend(list(p.rglob(ext)))
        if "maildir" in str(p):
            # Sample leaf files from maildir
            leaf_files = [f for f in p.rglob("*") if f.is_file() and not f.name.endswith((".py", ".pyc", ".json", ".md"))]
            discovered_files.extend(leaf_files[:max_scan_files])

    # Remove duplicates preserving order
    seen_paths: Set[str] = set()
    unique_files: List[Path] = []
    for f in discovered_files:
        if str(f.resolve()) not in seen_paths:
            seen_paths.add(str(f.resolve()))
            unique_files.append(f)

    results: Dict[str, Any] = {
        "discovered": len(unique_files),
        "ingested": {},
        "discarded": {},
        "failed": {},
    }

    for file_path in unique_files:
        doc_name = file_path.name
        try:
            sender, recipients, subject, date_str, body = parse_raw_email_file(file_path)
            
            # Step 2: Machine Relevance Quality Filter
            is_relevant, reason = is_machine_relevant_email(body, subject=subject, sender=sender)
            
            if not is_relevant:
                _discarded_emails[doc_name] = reason
                results["discarded"][doc_name] = reason
                continue
                
            # Step 3: Accepted Machine Email -> Ingest Chunks into Vector Store
            formatted_email = (
                f"Subject: {subject}\n"
                f"From: {sender}\n"
                f"To: {recipients}\n"
                f"Date: {date_str}\n\n"
                f"Body:\n{body}"
            )
            
            chunks = pipeline.ingest_file(
                filename=doc_name,
                content_bytes=formatted_email.encode("utf-8"),
            )
            
            if not chunks:
                results["failed"][doc_name] = "0 extractable chunks"
                continue
                
            _ingested_emails[doc_name] = {
                "chunks": len(chunks),
                "sender": sender,
                "recipients": recipients,
                "subject": subject,
                "date": date_str,
                "path": str(file_path.relative_to(PROJECT_ROOT) if PROJECT_ROOT in file_path.parents else file_path),
            }
            results["ingested"][doc_name] = len(chunks)
            
            # Step 4: Extract and Link Knowledge Graph Entities
            _link_email_knowledge_graph(pipeline, doc_name, sender, recipients, subject, date_str, body)
            
        except Exception as exc:
            results["failed"][doc_name] = str(exc)

    return {
        "ingested_count": len(results["ingested"]),
        "discarded_count": len(results["discarded"]),
        "emails": results["ingested"],
        "discarded": results["discarded"],
        "failed": results["failed"],
    }


def _link_email_knowledge_graph(
    pipeline: Any,
    filename: str,
    sender: str,
    recipients: str,
    subject: str,
    date_str: str,
    body: str,
) -> None:
    """Builds typed Neo4j graph nodes and relations for a verified machine email."""
    config_entry = CONCEPTS_PER_EMAIL.get(filename, {})
    
    # 1. Email Node
    email_node_id = f"email:{filename}"
    clean_sender = config_entry.get("sender", re.sub(r"<.*?>", "", sender).strip() or "Technician")
    
    nodes: List[Dict[str, Any]] = [
        {
            "id": email_node_id,
            "name": subject or filename,
            "type": "Email",
            "properties": {
                "subject": subject,
                "from": clean_sender,
                "to": recipients,
                "date": date_str,
                "path": f"knowledge_docs/emails/{filename}",
                "body": body[:500],
            },
        }
    ]
    edges: List[Dict[str, Any]] = []

    # 2. Person (Sender) -> SENT -> Email
    person_sender_id = f"person:{clean_sender.lower().replace(' ', '_')}"
    nodes.append({
        "id": person_sender_id,
        "name": clean_sender,
        "type": "Person",
        "properties": {"role": "Machining Engineer / Operator", "email": sender},
    })
    edges.append({
        "source_id": person_sender_id,
        "target_id": email_node_id,
        "type": "SENT",
    })

    # 3. Person (Recipients) -> RECEIVED -> Email
    for recipient_raw in config_entry.get("recipients", [r.strip() for r in recipients.split(",") if r.strip()]):
        rec_clean = re.sub(r"<.*?>", "", recipient_raw).strip()
        if rec_clean and rec_clean.lower() != clean_sender.lower():
            rec_id = f"person:{rec_clean.lower().replace(' ', '_')}"
            nodes.append({
                "id": rec_id,
                "name": rec_clean,
                "type": "Person",
                "properties": {"role": "Collaborator / Lab Staff"},
            })
            edges.append({
                "source_id": rec_id,
                "target_id": email_node_id,
                "type": "RECEIVED",
            })

    # 4. MENTIONS -> Components
    components = config_entry.get("components", [])
    if not components:
        # Auto-extract components from text
        for comp in ["Spindle", "Load Cell", "Dynamometer", "Accelerometer", "Cutter", "Bearing"]:
            if comp.lower() in body.lower() or comp.lower() in subject.lower():
                components.append(comp)
                
    for comp in components:
        comp_id = f"component:{comp.lower().replace(' ', '_')}"
        nodes.append({"id": comp_id, "name": comp, "type": "Component"})
        edges.append({"source_id": email_node_id, "target_id": comp_id, "type": "MENTIONS"})

    # 5. MENTIONS -> Faults
    faults = config_entry.get("faults", [])
    for fault in faults:
        fault_id = f"fault:{fault.lower().replace(' ', '_')}"
        nodes.append({"id": fault_id, "name": fault, "type": "Fault"})
        edges.append({"source_id": email_node_id, "target_id": fault_id, "type": "MENTIONS"})

    # 6. MENTIONS / CORROBORATES -> Process Condition
    condition_id = config_entry.get("condition_id")
    if not condition_id:
        cond_match = re.search(r"\bcondition\s*(\d+)\b", f"{subject} {body}", re.IGNORECASE)
        if cond_match:
            condition_id = cond_match.group(1)
            
    if condition_id and condition_id != "all":
        cond_node_id = f"condition:{condition_id}"
        nodes.append({"id": cond_node_id, "name": f"Condition {condition_id}", "type": "Condition"})
        edges.append({"source_id": email_node_id, "target_id": cond_node_id, "type": "MENTIONS"})
        edges.append({"source_id": email_node_id, "target_id": cond_node_id, "type": "CORROBORATES"})

    # Ingest graph elements into active knowledge graph store
    pipeline.ingest_graph_elements(nodes, edges)

    # Also directly populate global neo4j store for multi-hop graph traversals
    for n in nodes:
        neo4j.merge_node(
            label=n.get("type", "Entity"),
            key="name",
            value=n.get("id", n.get("name", "")),
            props=n.get("properties", {}),
        )
    for e in edges:
        neo4j.merge_edge(
            source=e.get("source_id", ""),
            target=e.get("target_id", ""),
            type=e.get("type", "RELATED_TO"),
            properties=e.get("properties", {}),
        )


def get_ingested_emails() -> Dict[str, Dict[str, Any]]:
    """Returns all successfully ingested machine emails."""
    return dict(_ingested_emails)


def get_discarded_emails() -> Dict[str, str]:
    """Returns all non-machine discarded emails and reasons."""
    return dict(_discarded_emails)


def emails_for_concepts(question: str) -> List[str]:
    """Finds machine emails linked to concepts or entities in the question."""
    q_lower = question.lower()
    matching_emails: List[str] = []
    
    for filename, info in _ingested_emails.items():
        subject = info.get("subject", "").lower()
        sender = info.get("sender", "").lower()
        cfg = CONCEPTS_PER_EMAIL.get(filename, {})
        
        # Check subject, sender, or concepts overlap
        if any(w in q_lower for w in subject.split() if len(w) > 3) or sender in q_lower:
            matching_emails.append(filename)
            continue
            
        for comp in cfg.get("components", []):
            if comp.lower() in q_lower:
                matching_emails.append(filename)
                break
                
        for conc in cfg.get("concepts", []):
            if conc.lower() in q_lower:
                if filename not in matching_emails:
                    matching_emails.append(filename)
                break
                
    return matching_emails
