"""Auto-register all parser plugins on import."""
from ingestion.parsers.pdf_parser import PDFParser
from ingestion.parsers.cad_parser import CADParser
from ingestion.parsers.email_parser import EmailParser
from ingestion.parsers.code_parser import PythonParser

__all__ = [
    "PDFParser",
    "CADParser",
    "EmailParser",
    "PythonParser"
]
