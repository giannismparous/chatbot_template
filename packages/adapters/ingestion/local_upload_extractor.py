from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DOCX_SETUP_MESSAGE = "DOCX extraction unavailable. Run pip install -r requirements.txt."


@dataclass
class ExtractionResult:
    text: str | None = None
    language: str = "unknown"
    unsupported: bool = False
    error: str | None = None
    reason: str | None = None
    error_stage: str | None = None
    error_code: str | None = None
    error_detail: str | None = None
    dependency_missing: bool = False


def file_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def extract_text(path: Path, raw_bytes: bytes | None = None) -> ExtractionResult:
    ext = file_extension(path.name)
    data = raw_bytes if raw_bytes is not None else path.read_bytes()

    if ext in (".txt", ".md", ".markdown"):
        return _extract_plain_text(data)

    if ext == ".pdf":
        return _extract_pdf(data)

    if ext == ".docx":
        return _extract_docx(data)

    return ExtractionResult(
        unsupported=True,
        reason=f"no extractor for extension {ext!r}",
        error_stage="extract",
        error_code="EXTENSION_NOT_ALLOWED",
        error_detail=f"no extractor for extension {ext!r}",
    )


def _extract_plain_text(data: bytes) -> ExtractionResult:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return ExtractionResult(text=data.decode(encoding))
        except UnicodeDecodeError:
            continue
    return ExtractionResult(
        error="unable to decode text file",
        error_stage="decode",
        error_code="DECODE_ERROR",
        error_detail="unable to decode text file",
    )


def _extract_pdf(data: bytes) -> ExtractionResult:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ExtractionResult(
            unsupported=True,
            reason="pdf extraction unavailable (install pypdf)",
            error_stage="pdf",
            error_code="DEPENDENCY_MISSING",
            error_detail="pdf extraction unavailable (install pypdf)",
            dependency_missing=True,
        )

    try:
        from io import BytesIO

        reader = PdfReader(BytesIO(data))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        text = "\n".join(pages).strip()
        if not text:
            return ExtractionResult(
                error="pdf contained no extractable text",
                error_stage="pdf",
                error_code="EMPTY_CONTENT",
                error_detail="pdf contained no extractable text",
            )
        return ExtractionResult(text=text)
    except Exception as exc:
        return ExtractionResult(
            error=f"pdf extraction failed: {exc}",
            error_stage="pdf",
            error_code="PDF_PARSE_ERROR",
            error_detail=f"pdf extraction failed: {exc}",
        )


def _extract_docx(data: bytes) -> ExtractionResult:
    try:
        from docx import Document
    except ImportError:
        return ExtractionResult(
            unsupported=True,
            reason=DOCX_SETUP_MESSAGE,
            error_stage="docx",
            error_code="DEPENDENCY_MISSING",
            error_detail=DOCX_SETUP_MESSAGE,
            dependency_missing=True,
        )

    try:
        from io import BytesIO

        document = Document(BytesIO(data))
        paragraphs = [p.text for p in document.paragraphs if p.text.strip()]
        text = "\n".join(paragraphs).strip()
        if not text:
            return ExtractionResult(
                error="docx contained no extractable text",
                error_stage="docx",
                error_code="EMPTY_CONTENT",
                error_detail="docx contained no extractable text",
            )
        return ExtractionResult(text=text)
    except Exception as exc:
        return ExtractionResult(
            error=f"docx extraction failed: {exc}",
            error_stage="docx",
            error_code="DOCX_PARSE_ERROR",
            error_detail=f"docx extraction failed: {exc}",
        )
