import os
from pathlib import Path
from typing import List, Dict, Any, Optional
import yaml
from pydantic import BaseModel, Field, model_validator

class GlossaryItem(BaseModel):
    term: str
    meaning: str = ""
    definition: str = ""

    @model_validator(mode="after")
    def sync_meaning_definition(self) -> 'GlossaryItem':
        if not self.meaning and self.definition:
            self.meaning = self.definition
        elif not self.definition and self.meaning:
            self.definition = self.meaning
        return self

class DomainConfig(BaseModel):
    domain_name: str = "Generic Industrial Plant"
    entity_types: List[str] = Field(default_factory=lambda: [
        "Equipment", "Procedure", "RegulatoryClause", "Person", "Incident", "Parameter"
    ])
    relation_types: List[str] = Field(default_factory=lambda: [
        "MAINTAINED_BY", "PART_OF", "MENTIONED_IN", "CAUSED_BY", "SUPERSEDES"
    ])
    glossary: List[GlossaryItem] = Field(default_factory=list)
    entity_aliases: Dict[str, str] = Field(default_factory=dict)
    system_prompt_template: str = (
        "You are a knowledge assistant for {domain_name}.\n"
        "Answer only using the provided context. Cite sources for every claim.\n"
        "If the context is insufficient, say so — never invent information."
    )

def get_project_root() -> Path:
    """Helper to locate the project root directory."""
    current = Path(__file__).resolve().parent
    for parent in [current] + list(current.parents):
        if (parent / "config").is_dir() or (parent / "requirements.txt").exists():
            return parent
    return current.parent

def load_domain_config(path: Optional[str] = None) -> DomainConfig:
    """Loads and validates the domain configuration from YAML.
    
    If the file does not exist or has invalid content, it falls back to the default configuration
    so that the system does not crash.
    """
    if path is None:
        project_root = get_project_root()
        path = str(project_root / "config" / "domain.yaml")
    
    if not os.path.exists(path):
        return DomainConfig()
        
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not data:
            return DomainConfig()
        return DomainConfig(**data)
    except Exception as e:
        print(f"Warning: Failed to load domain config from {path} due to: {e}. Using default domain config.")
        return DomainConfig()

# Global configuration instance loaded once
DOMAIN = load_domain_config()

def save_domain_config(new_config: dict, path: Optional[str] = None) -> None:
    """Saves a new domain configuration dictionary into domain.yaml."""
    if path is None:
        project_root = get_project_root()
        path = str(project_root / "config" / "domain.yaml")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(new_config, f, default_flow_style=False, allow_unicode=True)

def reload_domain_config(path: Optional[str] = None) -> None:
    """Reloads the active domain configuration from path."""
    global DOMAIN
    DOMAIN = load_domain_config(path)

