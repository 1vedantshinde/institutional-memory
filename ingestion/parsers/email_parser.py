"""Email index parser plugin."""
from typing import Dict, Any, Optional
import email
from email import policy
from core.registry import register_parser, BaseParser
from core.schema import UnifiedDocument, make_doc_id

@register_parser("eml", "mbox", "msg")
class EmailParser(BaseParser):
    """Parses email archives (.eml, .mbox, .msg raw data) into a UnifiedDocument."""
    
    def parse(self, filename: str, content_bytes: bytes, metadata: Optional[Dict[str, Any]] = None) -> UnifiedDocument:
        meta = metadata or {}
        sender = "Unknown"
        recipient = "Unknown"
        subject = "No Subject"
        date = ""
        body = ""
        
        try:
            # Parse standard MIME message from raw bytes
            msg = email.message_from_bytes(content_bytes, policy=policy.default)
            sender = msg.get('From', 'Unknown')
            recipient = msg.get('To', 'Unknown')
            subject = msg.get('Subject', 'No Subject')
            date = msg.get('Date', '')
            
            # Recursively walk email message parts to find plain text body
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
                body = "[No plain text content found in email]"
                
        except Exception as e:
            body = f"Failed to parse email message content: {str(e)}"
            
        full_content = f"Subject: {subject}\nFrom: {sender}\nTo: {recipient}\nDate: {date}\n\nBody:\n{body}"
        
        doc_meta = {
            **meta,
            "parsed_by": "EmailParser",
            "email_headers": {
                "from": sender,
                "to": recipient,
                "subject": subject,
                "date": date
            }
        }
        
        modality = "email"
        return UnifiedDocument(
            doc_id=make_doc_id(modality, filename),
            modality=modality,
            source_path=filename,
            raw_content=full_content,
            metadata=doc_meta
        )
