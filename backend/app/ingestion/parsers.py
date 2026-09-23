"""
Parsing layer: raw bytes -> list of ParsedUnit (one per page/section, so
downstream chunking can preserve page numbers for citations).

Each parser is intentionally dumb and single-purpose. The pipeline
(app/ingestion/pipeline.py) picks the parser by content_type — that's the
only coupling point, so adding a new format later means adding one
function here and one line in the dispatch table.
"""

from dataclasses import dataclass
from io import BytesIO

import docx
from pypdf import PdfReader

from app.core.exceptions import IngestionError


@dataclass
class ParsedUnit:
    text: str
    page_number: int | None = None
    section_title: str | None = None


def parse_pdf(content: bytes, document_id: str) -> list[ParsedUnit]:
    try:
        reader = PdfReader(BytesIO(content))
    except Exception as exc:
        raise IngestionError(document_id, f"Failed to open PDF: {exc}") from exc

    units: list[ParsedUnit] = []
    for page_index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            # One bad page shouldn't kill the whole document — skip and continue.
            text = ""
        if text.strip():
            units.append(ParsedUnit(text=text, page_number=page_index))

    if not units:
        raise IngestionError(document_id, "No extractable text found in PDF (may be scanned/image-only).")
    return units


def parse_docx(content: bytes, document_id: str) -> list[ParsedUnit]:
    try:
        d = docx.Document(BytesIO(content))
    except Exception as exc:
        raise IngestionError(document_id, f"Failed to open DOCX: {exc}") from exc

    units: list[ParsedUnit] = []
    current_section: str | None = None
    buffer: list[str] = []

    def flush():
        if buffer:
            units.append(ParsedUnit(text="\n".join(buffer), section_title=current_section))
            buffer.clear()

    for para in d.paragraphs:
        style = (para.style.name or "").lower() if para.style else ""
        if style.startswith("heading"):
            flush()
            current_section = para.text.strip() or current_section
            buffer.append(para.text)  # keep heading text in its own section too
        elif para.text.strip():
            buffer.append(para.text)
    flush()

    if not units:
        raise IngestionError(document_id, "No extractable text found in DOCX.")
    return units


def parse_text(content: bytes, document_id: str) -> list[ParsedUnit]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IngestionError(document_id, f"File is not valid UTF-8 text: {exc}") from exc

    if not text.strip():
        raise IngestionError(document_id, "File is empty.")
    return [ParsedUnit(text=text)]


PARSERS = {
    "application/pdf": parse_pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": parse_docx,
    "text/plain": parse_text,
    "text/markdown": parse_text,
}


def parse_document(content_type: str, content: bytes, document_id: str) -> list[ParsedUnit]:
    parser = PARSERS.get(content_type)
    if parser is None:
        raise IngestionError(document_id, f"No parser registered for content type '{content_type}'.")
    return parser(content, document_id)
