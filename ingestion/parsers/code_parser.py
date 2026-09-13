"""Python source code parser plugin."""
from typing import Dict, Any, Optional
from core.registry import register_parser, BaseParser
from core.schema import UnifiedDocument, make_doc_id

@register_parser("py")
class PythonParser(BaseParser):
    """Parses Python source files into a UnifiedDocument with modality='code'."""

    def parse(self, filename: str, content_bytes: bytes, metadata: Optional[Dict[str, Any]] = None) -> UnifiedDocument:
        meta = metadata or {}
        try:
            content = content_bytes.decode("utf-8", errors="ignore")
        except Exception:
            content = ""

        doc_meta = {**meta, "parsed_by": "PythonParser"}
        modality = "code"
        return UnifiedDocument(
            doc_id=make_doc_id(modality, filename),
            modality=modality,
            source_path=filename,
            raw_content=content,
            metadata=doc_meta
        )
