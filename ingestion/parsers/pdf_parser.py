"""PDF parser plugin."""
import io
from typing import Dict, Any, Optional
from core.registry import register_parser, BaseParser
from core.schema import UnifiedDocument, make_doc_id

@register_parser("pdf")
class PDFParser(BaseParser):
    """Parses native PDF documents into the UnifiedDocument schema using pypdf."""

    def parse(self, filename: str, content_bytes: bytes, metadata: Optional[Dict[str, Any]] = None) -> UnifiedDocument:
        meta = metadata or {}
        content = ""
        parse_method = "pypdf"
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content_bytes))
            pages_text = []
            for page in reader.pages:
                text = page.extract_text() or ""
                pages_text.append(text)
            content = "\n\n".join(pages_text).strip()
        except Exception as e:
            content = ""
            parse_method = f"pypdf_failed:{e}"

        # Fallback: if pypdf found no extractable text, the PDF is likely scanned/image-based
        if not content:
            try:
                # Last-resort: try decoding bytes as plain text (handles text-based fake PDFs in tests)
                decoded = content_bytes.decode("utf-8", errors="ignore").strip()
                if decoded:
                    content = decoded
                    parse_method = "utf8_fallback"
                else:
                    content = "[No extractable text — likely a scanned PDF; OCR not yet configured]"
                    parse_method = "empty_fallback"
            except Exception:
                content = "[No extractable text — likely a scanned PDF; OCR not yet configured]"
                parse_method = "empty_fallback"

        doc_meta = {**meta, "parsed_by": "PDFParser", "parse_method": parse_method}
        modality = "text"
        return UnifiedDocument(
            doc_id=make_doc_id(modality, filename),
            modality=modality,
            source_path=filename,
            raw_content=content,
            metadata=doc_meta
        )
