"""
email_gateway/parser.py
Parse incoming MIME emails: extract headers, plain text body,
and attachments (PDF, Excel, image).
"""
import email
import io
from dataclasses import dataclass, field
from email.message import Message
from typing import Optional

import pdfplumber
import openpyxl
import pytesseract
from PIL import Image
from bs4 import BeautifulSoup

from logger import get_logger

logger = get_logger(__name__)


@dataclass
class ParsedEmail:
    message_id: str
    in_reply_to: Optional[str]
    subject: str
    from_email: str
    to_email: str
    body: str
    attachments: list[dict] = field(default_factory=list)
    """Each attachment: {"filename": str, "content_type": str, "text": str, "raw": bytes}"""


class EmailParser:
    """Parse a raw MIME bytes message into a structured ParsedEmail."""

    def parse(self, raw_bytes: bytes) -> ParsedEmail:
        msg: Message = email.message_from_bytes(raw_bytes)

        parsed = ParsedEmail(
            message_id=msg.get("Message-ID", "").strip(),
            in_reply_to=msg.get("In-Reply-To", "").strip() or None,
            subject=self._decode_header(msg.get("Subject", "")),
            from_email=email.utils.parseaddr(msg.get("From", ""))[1],
            to_email=email.utils.parseaddr(msg.get("To", ""))[1],
            body="",
        )

        text_parts: list[str] = []
        for part in msg.walk():
            ct = part.get_content_type()
            disposition = part.get("Content-Disposition", "")

            if "attachment" in disposition:
                self._handle_attachment(part, parsed)
            elif ct == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    text_parts.append(payload.decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    ))
            elif ct == "text/html" and not text_parts:
                payload = part.get_payload(decode=True)
                if payload:
                    html = payload.decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                    text_parts.append(self._html_to_text(html))

        parsed.body = "\n".join(text_parts).strip()
        return parsed

    # ── Private helpers ───────────────────────────────────────────

    def _handle_attachment(self, part: Message, parsed: ParsedEmail):
        filename = part.get_filename() or "attachment"
        ct = part.get_content_type()
        raw = part.get_payload(decode=True) or b""
        text = ""

        try:
            if ct == "application/pdf" or filename.lower().endswith(".pdf"):
                text = self._extract_pdf(raw)
            elif ct in (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/vnd.ms-excel",
            ) or filename.lower().endswith((".xlsx", ".xls")):
                text = self._extract_excel(raw)
            elif ct.startswith("image/"):
                text = self._extract_image_ocr(raw)
        except Exception as exc:
            logger.warning("Attachment parse failed", extra={"filename": filename, "error": str(exc)})

        parsed.attachments.append({
            "filename": filename,
            "content_type": ct,
            "text": text,
            "raw": raw,
        })

    @staticmethod
    def _extract_pdf(raw: bytes) -> str:
        text_parts = []
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        return "\n".join(text_parts)

    @staticmethod
    def _extract_excel(raw: bytes) -> str:
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        rows = []
        for sheet in wb.worksheets:
            for row in sheet.iter_rows(values_only=True):
                row_str = " | ".join(str(c) for c in row if c is not None)
                if row_str.strip():
                    rows.append(row_str)
        return "\n".join(rows)

    @staticmethod
    def _extract_image_ocr(raw: bytes) -> str:
        img = Image.open(io.BytesIO(raw))
        return pytesseract.image_to_string(img, lang="fra+eng")

    @staticmethod
    def _html_to_text(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text(separator="\n")

    @staticmethod
    def _decode_header(value: str) -> str:
        parts = email.header.decode_header(value)
        decoded = []
        for part, enc in parts:
            if isinstance(part, bytes):
                decoded.append(part.decode(enc or "utf-8", errors="replace"))
            else:
                decoded.append(part)
        return "".join(decoded)
