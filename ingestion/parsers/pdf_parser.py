"""PDF parser plugin."""
from typing import Dict, Any, Optional
from core.registry import register_parser, BaseParser
from core.schema import UnifiedDocument, make_doc_id

@register_parser("pdf")
class PDFParser(BaseParser):
    """Parses native or scanned PDF documents into the UnifiedDocument schema."""
    
    def parse(self, filename: str, content_bytes: bytes, metadata: Optional[Dict[str, Any]] = None) -> UnifiedDocument:
        meta = metadata or {}
        # In a real environment, you'd use Docling or PyPDF/Tesseract here.
        # For demonstration/stubbing, we decode the text if possible or simulate logic.
        try:
            content = content_bytes.decode("utf-8", errors="ignore")
        except Exception:
            content = "Binary PDF Content Placeholder"
            
        doc_meta = {
            **meta,
            "parsed_by": "PDFParser",
        }
        
        modality = "text"
        return UnifiedDocument(
            doc_id=make_doc_id(modality, filename),
            modality=modality,
            source_path=filename,
            raw_content=content,
            metadata=doc_meta
        )
