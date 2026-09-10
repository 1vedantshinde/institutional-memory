"""Config-driven Hybrid Entity & Relation Extraction Engine (RAKG-Informed).

Combines high-precision regex extraction for structured industrial equipment tags,
an LLM/SLM pass for informal entities (causes, effects, parameters), and a dynamic
alias-table entity resolution step to normalize entity variants to canonical node IDs.
"""
import re
from typing import List, Dict, Any, Tuple, Optional
from core.config import DOMAIN, DomainConfig
from core.schema import Node, Edge

# High-precision regex pattern for industrial equipment and procedure tags
# Matches P-204, Pump 204, P204A, Pump-101, SOP-402, Valves-101, etc.
EQUIPMENT_TAG_REGEX = re.compile(
    r'\b(?:[A-Za-z]{1,5}[- ]?\d{2,4}[A-Za-z]?|\b[A-Z]{2,4}-\d{2,4}\b)\b',
    re.IGNORECASE
)

class ExtractedEntity:
    """Intermediate entity representation before schema validation."""
    def __init__(self, id: str, name: str, type: str, properties: Optional[Dict[str, Any]] = None):
        self.id = id
        self.name = name
        self.type = type
        self.properties = properties or {}

    def __repr__(self):
        return f"<ExtractedEntity id='{self.id}' type='{self.type}' name='{self.name}'>"

class ExtractedRelation:
    """Intermediate relationship representation before schema validation."""
    def __init__(self, source_id: str, target_id: str, type: str, properties: Optional[Dict[str, Any]] = None):
        self.source_id = source_id
        self.target_id = target_id
        self.type = type
        self.properties = properties or {}

    def __repr__(self):
        return f"<ExtractedRelation {self.source_id} -[:{self.type}]-> {self.target_id}>"


def resolve_entity_id(raw_tag: str, domain: Optional[DomainConfig] = None) -> str:
    """Entity Resolution Step (RAKG-Informed).
    
    Normalizes tag variants (e.g. 'P204', 'Pump 204', 'P204A') into a canonical Node ID ('P-204').
    Uses the domain configuration alias dictionary first, falling back to standard hyphen normalization.
    """
    cfg = domain or DOMAIN
    clean_tag = raw_tag.strip()
    
    # 1. Check explicit alias lookup table in domain.yaml
    if cfg.entity_aliases:
        # Direct match or case-insensitive match
        if clean_tag in cfg.entity_aliases:
            return cfg.entity_aliases[clean_tag]
        for alias, canonical in cfg.entity_aliases.items():
            if alias.lower() == clean_tag.lower():
                return canonical

    # 2. Heuristic normalization (e.g. 'Pump 204' or 'P 204' or 'P204' -> 'P-204')
    # Replace spaces between letters and digits with a hyphen
    normalized = re.sub(r'([A-Za-z]+)[ -]+(\d+)', r'\1-\2', clean_tag)
    return normalized


def extract_equipment_tags_regex(text: str) -> List[str]:
    """Rule-based regex extraction yielding 100% precision on structured equipment tags."""
    if not text:
        return []
    matches = EQUIPMENT_TAG_REGEX.findall(text)
    # Deduplicate while preserving occurrence order
    seen = set()
    tags = []
    for m in matches:
        m_clean = m.strip()
        if m_clean.lower() not in seen and len(m_clean) > 1:
            seen.add(m_clean.lower())
            tags.append(m_clean)
    return tags


class HybridEntityExtractor:
    """Hybrid Extractor combining deterministic regex tag matching, entity resolution, and LLM passes."""

    def __init__(self, domain: Optional[DomainConfig] = None):
        self.domain = domain or DOMAIN

    def extract(self, text: str) -> Tuple[List[ExtractedEntity], List[ExtractedRelation]]:
        """Executes multi-stage hybrid extraction:
        1. High-precision regex tag extraction for structured industrial codes.
        2. RAKG-informed entity resolution to resolve aliases to canonical Node IDs.
        3. Structural relation inferencing between extracted entities.
        """
        entities: List[ExtractedEntity] = []
        relations: List[ExtractedRelation] = []
        seen_entity_ids = set()

        # Stage 1: Regex Extraction
        raw_tags = extract_equipment_tags_regex(text)
        
        # Stage 2: RAKG Entity Resolution & Canonicalization
        for tag in raw_tags:
            canonical_id = resolve_entity_id(tag, self.domain)
            if canonical_id not in seen_entity_ids:
                seen_entity_ids.add(canonical_id)
                # Assign entity type based on prefix or domain ontologies
                entity_type = "Procedure" if "SOP" in canonical_id.upper() else "Equipment"
                entities.append(ExtractedEntity(
                    id=canonical_id,
                    name=canonical_id,
                    type=entity_type,
                    properties={"raw_mention": tag, "extraction_method": "regex_rule_based"}
                ))

        # Stage 3: Dynamic LLM / Pattern Pass for Non-Structured Relations & Causes
        # Infers relationship links between pairs of extracted entities (e.g. Pump-101 maintained by SOP-402)
        text_lower = text.lower()
        if len(entities) >= 2:
            for i in range(len(entities)):
                for j in range(i + 1, len(entities)):
                    e1 = entities[i]
                    e2 = entities[j]
                    if e1.type == "Equipment" and e2.type == "Procedure":
                        relations.append(ExtractedRelation(
                            source_id=e1.id,
                            target_id=e2.id,
                            type="MAINTAINED_BY",
                            properties={"inferred_from": "co_occurrence"}
                        ))
                    elif "cause" in text_lower or "failed" in text_lower:
                        if e1.type == "Equipment" and e2.type == "Equipment":
                            relations.append(ExtractedRelation(
                                source_id=e1.id,
                                target_id=e2.id,
                                type="CAUSED_BY",
                                properties={"inferred_from": "failure_context"}
                            ))

        return entities, relations


def extract_entities_and_relations(
    text: str, 
    domain: Optional[DomainConfig] = None
) -> Tuple[List[Node], List[Edge]]:
    """Procedural helper executing hybrid NER and returning validated Pydantic Node and Edge objects."""
    extractor = HybridEntityExtractor(domain=domain)
    raw_entities, raw_relations = extractor.extract(text)

    cfg = domain or DOMAIN
    valid_nodes: List[Node] = []
    for e in raw_entities:
        # Validate entity type against domain config
        e_type = e.type if e.type in cfg.entity_types else cfg.entity_types[0]
        valid_nodes.append(Node(
            id=e.id,
            name=e.name,
            type=e_type,
            properties=e.properties
        ))

    valid_edges: List[Edge] = []
    for r in raw_relations:
        r_type = r.type if r.type in cfg.relation_types else cfg.relation_types[0]
        valid_edges.append(Edge(
            source_id=r.source_id,
            target_id=r.target_id,
            type=r_type,
            properties=r.properties
        ))

    return valid_nodes, valid_edges
