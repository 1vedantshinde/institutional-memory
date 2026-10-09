"""Query Intent & Entity Understanding (Step 1).

Extracts typed ontology entities (Components, Sessions, Channels, Persons, Faults,
Processes, Parameters, Procedures, Concepts, DateRanges) and query intent.
Consumes the unified ontology and serves as:
1. The input gate for Section 7's CNC scope validation.
2. The seed generator for Step 3's multi-hop graph traversal.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from core.config import DOMAIN, DomainConfig
from knowledge.ontology import (
    channel_node_id,
    component_node_id,
    concept_node_id,
    condition_node_id,
    event_node_id,
    fault_node_id,
    organization_node_id,
    parameter_node_id,
    person_node_id,
    procedure_node_id,
    process_node_id,
    session_node_id,
)
from knowledge.provenance import Provenance, make_provenance
from knowledge.session_ids import resolve_session_reference, SessionReference


class QueryIntent(str, Enum):
    """Classified user query intent category."""

    CROSS_SOURCE_CORRELATION = "cross_source_correlation"  # e.g., session + email / document cross-reference
    SESSION_DIAGNOSTIC = "session_diagnostic"              # e.g., session 42 anomaly or health
    ANOMALY_LOOKUP = "anomaly_lookup"                      # e.g., channel vibration spike in condition
    COMPONENT_STATUS = "component_status"                  # e.g., spindle bearing health / wear
    ORGANIZATIONAL_EMAIL = "organizational_email"          # e.g., email threads, custodian communications
    DOCUMENT_PROCEDURE = "document_procedure"              # e.g., SOP, maintenance procedure, policy
    GENERAL_KNOWLEDGE = "general_knowledge"                # e.g., glossary terms, machine principles
    OUT_OF_SCOPE = "out_of_scope"                          # non-CNC / external questions


class ExtractedEntity(BaseModel):
    """An entity recognized in the query matching the unified ontology."""

    entity_type: str  # "Component", "Session", "Condition", "Channel", "Person", "Organization", "Fault", "Process", "Parameter", "Procedure", "Concept", "DateRange"
    text: str
    canonical_id: str
    start_char: int = -1
    end_char: int = -1
    confidence: float = 1.0
    extraction_method: str = "rule_based"
    properties: Dict[str, Any] = Field(default_factory=dict)
    provenance: Optional[Provenance] = None


class QueryUnderstandingResult(BaseModel):
    """Complete semantic and entity representation of a user query."""

    query: str
    intent: QueryIntent
    entities: List[ExtractedEntity] = Field(default_factory=list)
    is_cnc_candidate: bool = False
    session_id: Optional[int] = None
    condition_id: Optional[str] = None
    channel: Optional[str] = None
    seed_node_ids: List[str] = Field(default_factory=list)
    temporal_scope: Optional[Dict[str, str]] = None
    provenance: Provenance = Field(
        default_factory=lambda: make_provenance("query", extraction_method="query_understanding")
    )

    def get_entities_by_type(self, entity_type: str) -> List[ExtractedEntity]:
        return [e for e in self.entities if e.entity_type.lower() == entity_type.lower()]


# =============================================================================
# Domain Vocabularies & Patterns
# =============================================================================

KNOWN_COMPONENTS = {
    "spindle": ["spindle", "spindle assembly", "main spindle", "high-speed spindle"],
    "spindle_motor": ["spindle motor", "drive motor", "motor"],
    "spindle_housing": ["spindle housing", "housing"],
    "spindle_bearing": ["spindle bearing", "spindle bearings", "bearing", "bearings", "ball bearing", "roller bearing"],
    "tool_holder": ["tool holder", "toolholder", "collet", "chuck", "arbor"],
    "cutting_tool": ["cutting tool", "end mill", "tool", "insert", "cutter", "carbide tool", "face mill"],
    "coolant_pump": ["coolant pump", "coolant system", "lubrication pump", "pump"],
    "machine_table": ["table", "machine table", "worktable", "bed", "workpiece table", "fixture table"],
    "dynamometer": ["dynamometer", "kistler dynamometer", "force table"],
    "accelerometer": ["accelerometer", "vibration sensor", "piezoelectric sensor"],
    "load_cell": ["load cell", "loadcell", "force sensor"],
    "cnc_machine": ["cnc", "cnc machine", "milling machine", "vibration testbed", "machine tool"],
}

KNOWN_FAULTS = {
    "tool_wear": ["tool wear", "flank wear", "crater wear", "nose wear", "wear", "worn tool", "worn"],
    "tool_breakage": ["tool breakage", "breakage", "tool chip", "chipping", "fracture", "broken tool"],
    "chatter": ["chatter", "chattering", "regenerative chatter", "machine chatter", "instability"],
    "bearing_fault": ["bearing fault", "bearing failure", "bearing damage", "inner race fault", "outer race fault", "ball defect"],
    "overheating": ["overheating", "thermal expansion", "thermal drift", "high temperature"],
    "vibration_spike": ["vibration spike", "abnormal vibration", "excessive vibration", "vibrational anomaly", "spike"],
    "imbalance": ["imbalance", "unbalance", "rotor unbalance", "misalignment", "eccentricity"],
    "cavitation": ["cavitation", "pump cavitation", "pressure drop"],
    "anomaly": ["anomaly", "abnormal", "deviation", "malfunction", "defect", "fault", "issue", "problem"],
}

KNOWN_PROCESSES = {
    "facing": ["facing", "face milling", "surface milling"],
    "pocketing": ["pocketing", "pocket milling"],
    "slotting": ["slotting", "slot milling"],
    "roughing": ["roughing", "rough cut", "rough machining"],
    "finishing": ["finishing", "finish cut", "fine machining"],
    "milling": ["milling", "cnc milling", "end milling", "machining", "cutting"],
    "drilling": ["drilling", "boring", "tapping"],
}

KNOWN_PARAMETERS = {
    "spindle_speed": ["spindle speed", "rotational speed", "rpm", "speed setting", "speed"],
    "feed_rate": ["feed rate", "feedrate", "feed", "linear feed", "mm/min"],
    "depth_of_cut": ["depth of cut", "doc", "axial depth", "radial depth", "ap", "ae"],
    "sampling_rate": ["sampling rate", "sampling frequency", "sample rate", "hz"],
    "rms": ["rms", "root mean square"],
    "peak": ["peak", "peak amplitude", "maximum value"],
    "crest_factor": ["crest factor"],
    "kurtosis": ["kurtosis"],
    "skewness": ["skewness"],
    "spectral_energy": ["spectral band energy", "band energy", "energy low", "energy mid", "energy high"],
    "spectral_centroid": ["spectral centroid"],
    "mahalanobis_distance": ["mahalanobis distance", "mahalanobis", "anomaly score"],
}

KNOWN_PROCEDURES = {
    "spindle_bearing_replacement": ["spindle bearing replacement", "bearing replacement", "replace spindle bearing"],
    "tool_change": ["tool change", "tool replacement", "cutter replacement", "tool setup"],
    "calibration": ["calibration", "sensor calibration", "dynamometer calibration"],
    "lubrication": ["lubrication", "greasing", "coolant top-up"],
    "quarantine_policy": ["quarantine policy", "quarantine procedure", "file quarantine", "schema validation"],
    "standard_operating_procedure": ["sop", "procedure", "operating procedure", "protocol", "maintenance procedure"],
}

CHANNEL_MAPPINGS = {
    "vib_spindle": "Vib_Spindle",
    "spindle vibration": "Vib_Spindle",
    "spindle vib": "Vib_Spindle",
    "vib_table": "Vib_Table",
    "table vibration": "Vib_Table",
    "table vib": "Vib_Table",
    "x_load_cell": "X_Load_Cell",
    "x load cell": "X_Load_Cell",
    "load cell x": "X_Load_Cell",
    "fx": "X_Load_Cell",
    "x-force": "X_Load_Cell",
    "y_load_cell": "Y_Load_Cell",
    "y load cell": "Y_Load_Cell",
    "load cell y": "Y_Load_Cell",
    "fy": "Y_Load_Cell",
    "y-force": "Y_Load_Cell",
    "z_load_cell": "Z_Load_Cell",
    "z load cell": "Z_Load_Cell",
    "load cell z": "Z_Load_Cell",
    "fz": "Z_Load_Cell",
    "z-force": "Z_Load_Cell",
    "current": "Current",
    "motor current": "Current",
    "spindle current": "Current",
    "time": "Time",
}

KNOWN_ORGANIZATIONS = {
    "cnc_lab": ["cnc lab", "machining lab", "machining-lab", "milling lab", "manufacturing facility", "plant", "maintenance team"],
    "mondragon": ["mondragon", "mondragon university", "mondragon-machining"],
    "kistler": ["kistler", "kistler dynamometer"],
    "deckel_maho": ["deckel maho", "deckel", "deckel-maho"],
    "enron": ["enron", "enron corp", "enron corporation"],
}

# Known machine engineers, technicians, and email correspondents
KNOWN_PERSONS = {
    # Machine personnel
    "marcus_vance": ["marcus vance", "marcus", "vance"],
    "dr_elena_rodriguez": ["dr. elena rodriguez", "dr elena rodriguez", "elena rodriguez", "rodriguez", "dr. rodriguez", "dr rodriguez"],
    "david_chen": ["david chen", "chen", "david"],
    "alex_rivera": ["alex rivera", "rivera", "alex"],
    "rachel_torres": ["rachel torres", "torres", "rachel"],
    "tom_bradley": ["tom bradley", "bradley", "tom"],
    "sarah_jenkins": ["sarah jenkins", "jenkins", "sarah"],
    # Historical / external correspondents
    "kenneth_lay": ["ken lay", "kenneth lay", "lay"],
    "jeffrey_skilling": ["jeff skilling", "jeffrey skilling", "skilling"],
    "vince_kaminski": ["vince kaminski", "kaminski"],
    "daren_farmer": ["daren farmer", "farmer"],
    "steven_kean": ["steven kean", "steve kean", "kean"],
    "john_sherriff": ["john sherriff", "sherriff"],
    "richard_causey": ["richard causey", "causey"],
    "andrew_fastow": ["andrew fastow", "fastow"],
    "john": ["john"],
    "smith": ["smith", "dr. smith"],
}

# Temporal regex
_ISO_DATE_REGEX = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_MONTH_YEAR_REGEX = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4})\b",
    re.IGNORECASE,
)
_YEAR_REGEX = re.compile(r"\b(19\d\d|20\d\d)\b")

# General Person Name regex heuristic for capital names in queries
_PERSON_HEURISTIC_REGEX = re.compile(
    r"\b(?:from|to|by|with|ask|did|contact|engineer|custodian|operator)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"
)


# =============================================================================
# Entity Extractor Functions
# =============================================================================

def _extract_dict_vocabulary(
    text: str,
    vocab: Dict[str, List[str]],
    entity_type: str,
    node_id_fn,
) -> List[ExtractedEntity]:
    """Scan query text against a normalized alias dictionary."""
    entities: List[ExtractedEntity] = []
    text_lower = text.lower()
    seen_keys: Set[str] = set()

    # Sort items by longest alias first to match specific multi-word phrases first
    for canonical_key, aliases in vocab.items():
        sorted_aliases = sorted(aliases, key=len, reverse=True)
        for alias in sorted_aliases:
            # Word boundary regex for exact token matching
            pattern = r"\b" + re.escape(alias.lower()) + r"\b"
            for match in re.finditer(pattern, text_lower):
                if canonical_key not in seen_keys:
                    seen_keys.add(canonical_key)
                    c_id = node_id_fn(canonical_key)
                    entities.append(
                        ExtractedEntity(
                            entity_type=entity_type,
                            text=text[match.start():match.end()],
                            canonical_id=c_id,
                            start_char=match.start(),
                            end_char=match.end(),
                            confidence=1.0 if alias == canonical_key else 0.95,
                            extraction_method="ontology_exact",
                            properties={"key": canonical_key, "matched_alias": alias},
                        )
                    )
                break  # matched this canonical key
    return entities


def _extract_channels(text: str) -> List[ExtractedEntity]:
    """Extract and normalize sensor channel mentions with phrase disambiguation."""
    entities: List[ExtractedEntity] = []
    text_lower = text.lower()
    seen_channels: Set[str] = set()

    # Disambiguation patterns for words like 'current' and 'time' that have common non-sensor meanings
    non_sensor_current_patterns = [
        r"\bcurrent\s+(?:stock|price|time|date|day|month|year|weather|location|version|president|ceo|population|trend|news|page|user|event|events)\b",
        r"\b(?:what|who|where)\s+is\s+the\s+current\b",
        r"\bcurrent\s+market\b",
    ]
    is_temporal_current = any(re.search(p, text_lower) for p in non_sensor_current_patterns)

    non_sensor_time_patterns = [
        r"\b(?:what|tell\s+me)\s+(?:is\s+)?the\s+time\b",
        r"\btime\s+in\s+[a-z]+\b",
        r"\bwhat\s+time\s+is\s+it\b",
    ]
    is_clock_time = any(re.search(p, text_lower) for p in non_sensor_time_patterns)

    for pattern_str, canonical_name in sorted(CHANNEL_MAPPINGS.items(), key=lambda x: len(x[0]), reverse=True):
        if pattern_str == "current" and is_temporal_current:
            continue
        if pattern_str == "time" and is_clock_time:
            continue

        pattern = r"\b" + re.escape(pattern_str) + r"\b"
        for match in re.finditer(pattern, text_lower):
            if canonical_name not in seen_channels:
                seen_channels.add(canonical_name)
                entities.append(
                    ExtractedEntity(
                        entity_type="Channel",
                        text=text[match.start():match.end()],
                        canonical_id=channel_node_id(canonical_name),
                        start_char=match.start(),
                        end_char=match.end(),
                        confidence=1.0,
                        extraction_method="ontology_exact",
                        properties={"channel_name": canonical_name},
                    )
                )
    return entities


def _extract_glossary_concepts(text: str, domain: Optional[DomainConfig] = None) -> List[ExtractedEntity]:
    """Extract glossary terms defined in domain.yaml."""
    cfg = domain or DOMAIN
    entities: List[ExtractedEntity] = []
    text_lower = text.lower()
    seen_terms: Set[str] = set()

    for item in cfg.glossary:
        term = item.term.strip()
        if not term:
            continue
        term_clean = term.lower()
        pattern = r"\b" + re.escape(term_clean) + r"\b"
        for match in re.finditer(pattern, text_lower):
            if term_clean not in seen_terms:
                seen_terms.add(term_clean)
                entities.append(
                    ExtractedEntity(
                        entity_type="Concept",
                        text=text[match.start():match.end()],
                        canonical_id=concept_node_id(term),
                        start_char=match.start(),
                        end_char=match.end(),
                        confidence=1.0,
                        extraction_method="glossary_match",
                        properties={"term": term, "definition": item.definition},
                    )
                )
    return entities


def _extract_sessions_and_conditions(text: str) -> Tuple[List[ExtractedEntity], Optional[int], Optional[str]]:
    """Extract Session and Condition entities using the session resolver."""
    entities: List[ExtractedEntity] = []
    extracted_session_id: Optional[int] = None
    extracted_condition_id: Optional[str] = None

    # Check session reference
    session_ref = resolve_session_reference(text)
    if session_ref:
        extracted_session_id = session_ref.session_id
        extracted_condition_id = session_ref.condition_id
        entities.append(
            ExtractedEntity(
                entity_type="Session",
                text=session_ref.matched_text,
                canonical_id=session_node_id(session_ref.session_id),
                confidence=1.0,
                extraction_method="session_resolver",
                properties={
                    "session_id": session_ref.session_id,
                    "condition_id": session_ref.condition_id,
                    "recording_number": session_ref.recording_number,
                },
            )
        )
        entities.append(
            ExtractedEntity(
                entity_type="Condition",
                text=f"condition {session_ref.condition_id}",
                canonical_id=condition_node_id(session_ref.condition_id),
                confidence=0.9,
                extraction_method="session_resolver_inferred",
                properties={"condition_id": session_ref.condition_id},
            )
        )

    # Also check standalone condition patterns if not already captured
    if not extracted_condition_id:
        cond_match = re.search(r"\b(?:condition|cond\.?|c)\s*(\d+)\b", text, re.IGNORECASE)
        if cond_match:
            cid = cond_match.group(1)
            extracted_condition_id = cid
            entities.append(
                ExtractedEntity(
                    entity_type="Condition",
                    text=cond_match.group(0),
                    canonical_id=condition_node_id(cid),
                    start_char=cond_match.start(),
                    end_char=cond_match.end(),
                    confidence=1.0,
                    extraction_method="regex_rule_based",
                    properties={"condition_id": cid},
                )
            )

    return entities, extracted_session_id, extracted_condition_id


def _extract_persons_and_orgs(text: str) -> List[ExtractedEntity]:
    """Extract Persons and Organizations from known directories and heuristics."""
    entities: List[ExtractedEntity] = []

    # Known Persons
    entities.extend(_extract_dict_vocabulary(text, KNOWN_PERSONS, "Person", person_node_id))

    # Known Orgs
    entities.extend(_extract_dict_vocabulary(text, KNOWN_ORGANIZATIONS, "Organization", organization_node_id))

    # Heuristic Person names (e.g. "email from John", "discussed by Alice")
    for match in _PERSON_HEURISTIC_REGEX.finditer(text):
        name = match.group(1).strip()
        p_id = person_node_id(name)
        if not any(e.canonical_id == p_id for e in entities):
            entities.append(
                ExtractedEntity(
                    entity_type="Person",
                    text=name,
                    canonical_id=p_id,
                    start_char=match.start(1),
                    end_char=match.end(1),
                    confidence=0.75,
                    extraction_method="heuristic_ner",
                    properties={"name": name},
                )
            )

    return entities


def _extract_dates(text: str) -> Tuple[List[ExtractedEntity], Optional[Dict[str, str]]]:
    """Extract temporal expressions."""
    entities: List[ExtractedEntity] = []
    scope: Optional[Dict[str, str]] = None

    for m in _ISO_DATE_REGEX.finditer(text):
        dt_str = m.group(1)
        entities.append(
            ExtractedEntity(
                entity_type="DateRange",
                text=dt_str,
                canonical_id=f"date:{dt_str}",
                start_char=m.start(),
                end_char=m.end(),
                confidence=1.0,
                extraction_method="regex_iso_date",
                properties={"date": dt_str},
            )
        )
        if not scope:
            scope = {"start": dt_str, "end": dt_str}

    for m in _MONTH_YEAR_REGEX.finditer(text):
        mon_yr = m.group(0)
        entities.append(
            ExtractedEntity(
                entity_type="DateRange",
                text=mon_yr,
                canonical_id=f"date:{mon_yr.lower().replace(' ', '_')}",
                start_char=m.start(),
                end_char=m.end(),
                confidence=0.9,
                extraction_method="regex_month_year",
                properties={"month_year": mon_yr},
            )
        )

    return entities, scope


# =============================================================================
# Intent Classification & Scope Determination
# =============================================================================

def _classify_intent(
    query: str,
    entities: List[ExtractedEntity],
    has_session: bool,
    has_email_or_person: bool,
    has_doc_concept: bool,
    has_fault_or_component: bool,
) -> QueryIntent:
    """Classify the user intent based on query structure and matched ontology entities."""
    q_lower = query.lower()

    # 1. Cross-source correlation: asks to connect machine/session data with email or documentation
    cross_source_triggers = [
        "related to the problem discussed in the email",
        "discussed in the email",
        "mentioned in email",
        "email discussing",
        "corroborate",
        "mentioned in documentation",
        "corresponds to",
        "align with email",
    ]
    has_cross_trigger = any(t in q_lower for t in cross_source_triggers)
    if (has_session or has_fault_or_component) and has_email_or_person and (has_cross_trigger or "email" in q_lower or "thread" in q_lower):
        return QueryIntent.CROSS_SOURCE_CORRELATION

    # 2. Email / Organizational inquiry
    if ("email" in q_lower or "sent" in q_lower or "received" in q_lower or "wrote" in q_lower or "thread" in q_lower) and has_email_or_person:
        return QueryIntent.ORGANIZATIONAL_EMAIL

    # 3. Session Diagnostic
    if has_session or "recording" in q_lower or "condition" in q_lower or "run " in q_lower:
        return QueryIntent.SESSION_DIAGNOSTIC

    # 4. Procedure / Documentation lookup
    procedure_entities = [e for e in entities if e.entity_type == "Procedure"]
    if procedure_entities or "procedure" in q_lower or "sop" in q_lower or "how to replace" in q_lower or "steps for" in q_lower:
        return QueryIntent.DOCUMENT_PROCEDURE

    # 5. Component Status / Fault inquiry
    if has_fault_or_component:
        return QueryIntent.COMPONENT_STATUS

    # 6. Check if query has any CNC entities or domain keywords
    cnc_keywords = {
        "cnc", "machine", "milling", "spindle", "tool", "vibration", "sensor", "bearing",
        "feed", "speed", "cut", "signal", "channel", "daq", "finding", "anomaly", "kurtosis",
        "maintenance", "quarantine", "rms", "load cell", "facing", "calibration", "flank wear",
        "pocketing", "mahalanobis", "sampling rate", "recording", "session", "condition"
    }
    has_any_cnc_word = any(w in q_lower for w in cnc_keywords)
    if not entities and not has_any_cnc_word:
        return QueryIntent.OUT_OF_SCOPE

    # 7. General Knowledge / Glossary (for in-domain concepts or general machine questions)
    concept_entities = [e for e in entities if e.entity_type in ("Concept", "Parameter")]
    if concept_entities or "what is" in q_lower or "explain" in q_lower or "define" in q_lower or "sampling rate" in q_lower:
        return QueryIntent.GENERAL_KNOWLEDGE

    return QueryIntent.GENERAL_KNOWLEDGE


# =============================================================================
# Main Entry Point: understand_query
# =============================================================================

def understand_query(
    query: str,
    domain: Optional[DomainConfig] = None,
) -> QueryUnderstandingResult:
    """Execute Step 1: Query Intent & Entity Understanding against the Unified Ontology.

    Extracts:
    - Component, Fault, Process, Parameter, Procedure, Channel entities
    - Session & Condition coordinates (Option A global session addressing)
    - Person, Organization, and Temporal scopes
    - Concept / Glossary terms
    - Query intent and candidate CNC scope status
    - Pre-computed seed node IDs for Step 3 graph traversal
    """
    clean_query = query.strip()
    entities: List[ExtractedEntity] = []

    # 1. Components
    entities.extend(_extract_dict_vocabulary(clean_query, KNOWN_COMPONENTS, "Component", component_node_id))

    # 2. Faults
    entities.extend(_extract_dict_vocabulary(clean_query, KNOWN_FAULTS, "Fault", fault_node_id))

    # 3. Processes
    entities.extend(_extract_dict_vocabulary(clean_query, KNOWN_PROCESSES, "Process", process_node_id))

    # 4. Parameters
    entities.extend(_extract_dict_vocabulary(clean_query, KNOWN_PARAMETERS, "Parameter", parameter_node_id))

    # 5. Procedures
    entities.extend(_extract_dict_vocabulary(clean_query, KNOWN_PROCEDURES, "Procedure", procedure_node_id))

    # 6. Channels
    channel_entities = _extract_channels(clean_query)
    entities.extend(channel_entities)

    # 7. Sessions and Conditions
    session_entities, sid, cid = _extract_sessions_and_conditions(clean_query)
    entities.extend(session_entities)

    # 8. Concepts & Glossary
    entities.extend(_extract_glossary_concepts(clean_query, domain=domain))

    # 9. Persons & Organizations
    person_org_entities = _extract_persons_and_orgs(clean_query)
    entities.extend(person_org_entities)

    # 10. Dates / Temporal
    date_entities, temporal_scope = _extract_dates(clean_query)
    entities.extend(date_entities)

    # Primary channel extraction
    extracted_channel: Optional[str] = None
    if channel_entities:
        extracted_channel = channel_entities[0].properties.get("channel_name")

    # Intent Classification
    has_session = sid is not None
    has_email_or_person = any(e.entity_type in ("Person", "Organization") for e in entities) or "email" in clean_query.lower()
    has_doc_concept = any(e.entity_type in ("Concept", "Procedure", "Document") for e in entities)
    has_fault_or_component = any(e.entity_type in ("Component", "Fault") for e in entities)

    intent = _classify_intent(
        clean_query,
        entities,
        has_session=has_session,
        has_email_or_person=has_email_or_person,
        has_doc_concept=has_doc_concept,
        has_fault_or_component=has_fault_or_component,
    )

    # CNC Scope Candidate Check:
    # Plausibly concerns: machine/components/processes/parameters/documentation/session/channel/person/email
    is_cnc = (
        intent != QueryIntent.OUT_OF_SCOPE
        and len(entities) > 0
    )
    if not is_cnc:
        # Fallback check for domain words
        cnc_domain_words = {
            "spindle", "cnc", "machine", "milling", "bearing", "sensor", "vibration",
            "cutting", "feed", "speed", "tool", "fault", "session", "recording",
            "condition", "channel", "finding", "quarantine", "kurtosis", "rms",
            "kistler", "dynamometer", "flank wear", "mondragon", "deckel"
        }
        if any(w in clean_query.lower() for w in cnc_domain_words):
            is_cnc = True

    # Build seed node IDs for Step 3 graph traversal
    # Collect unique canonical IDs from extracted entities
    seed_node_ids: List[str] = []
    seen_seeds: Set[str] = set()
    for e in entities:
        if e.canonical_id and e.canonical_id not in seen_seeds:
            seen_seeds.add(e.canonical_id)
            seed_node_ids.append(e.canonical_id)

    # Attach provenance
    prov = make_provenance(
        source_type="query",
        source_path=clean_query,
        extraction_method="query_understanding",
        confidence=1.0,
    )
    for e in entities:
        e.provenance = prov

    return QueryUnderstandingResult(
        query=clean_query,
        intent=intent,
        entities=entities,
        is_cnc_candidate=is_cnc,
        session_id=sid,
        condition_id=cid,
        channel=extracted_channel,
        seed_node_ids=seed_node_ids,
        temporal_scope=temporal_scope,
        provenance=prov,
    )
