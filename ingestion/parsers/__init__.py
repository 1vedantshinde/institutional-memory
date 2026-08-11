"""Auto-register all parser plugins on import."""
from ingestion.parsers.pdf_parser import PDFParser
from ingestion.parsers.cad_parser import CADParser
from ingestion.parsers.email_parser import EmailParser

# We list them to make them available directly from ingestion.parsers
__all__ = [
    "PDFParser",
    "CADParser",
    "EmailParser"
]
