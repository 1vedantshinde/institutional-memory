"""CAD/DXF parser plugin."""
import io
from typing import Dict, Any, Optional
from core.registry import register_parser, BaseParser
from core.schema import UnifiedDocument, make_doc_id

try:
    import ezdxf
    HAS_EZDXF = True
except ImportError:
    HAS_EZDXF = False

@register_parser("dxf")
class CADParser(BaseParser):
    """Parses DXF (AutoCAD text/vector) files into UnifiedDocument.
    
    Reads layers, blocks, and textual entities dynamically.
    """
    
    def parse(self, filename: str, content_bytes: bytes, metadata: Optional[Dict[str, Any]] = None) -> UnifiedDocument:
        meta = metadata or {}
        extracted_text = []
        layers_found = set()
        
        if HAS_EZDXF:
            try:
                # Read string stream from content bytes
                text_content = content_bytes.decode("utf-8", errors="ignore")
                doc = ezdxf.read(io.StringIO(text_content))
                msp = doc.modelspace()
                
                # Extract text elements (TEXT, MTEXT) and block-insert tags
                for entity in msp:
                    layers_found.add(entity.dxf.layer)
                    if entity.dxftype() == 'TEXT':
                        text_val = entity.dxf.text
                        if text_val:
                            extracted_text.append(f"Layer [{entity.dxf.layer}]: {text_val}")
                    elif entity.dxftype() == 'MTEXT':
                        text_val = entity.text
                        if text_val:
                            extracted_text.append(f"Layer [{entity.dxf.layer}]: {text_val}")
                    elif entity.dxftype() == 'INSERT':
                        extracted_text.append(f"BlockRef [{entity.dxf.name}] at {entity.dxf.insert}")
            except Exception as e:
                extracted_text.append(f"Error parsing DXF with ezdxf: {str(e)}")
        else:
            # Simple fallback scanner for group codes if ezdxf is missing
            try:
                lines = content_bytes.decode("utf-8", errors="ignore").splitlines()
                # Scaning for group code '1' (text value) or group code '2' (name/block)
                for i in range(len(lines) - 1):
                    group_code = lines[i].strip()
                    val = lines[i+1].strip()
                    if group_code == "1":
                        extracted_text.append(f"Extracted Text: {val}")
                    elif group_code == "2":
                        extracted_text.append(f"Block Reference: {val}")
            except Exception as e:
                extracted_text.append(f"Fallback ASCII CAD parser error: {str(e)}")
                
        content = "\n".join(extracted_text) if extracted_text else "Empty CAD file content"
        
        doc_meta = {
            **meta,
            "parsed_by": "CADParser",
            "ezdxf_loaded": HAS_EZDXF,
            "detected_layers": list(layers_found)
        }
        
        modality = "cad"
        return UnifiedDocument(
            doc_id=make_doc_id(modality, filename),
            modality=modality,
            source_path=filename,
            raw_content=content,
            metadata=doc_meta
        )
