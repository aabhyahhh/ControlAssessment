"""
Lightweight text extraction for uploaded documents — docx/pdf/txt only, no
OCR for v1. Shared by SOP ingestion (Phase 3) and, if needed later,
evidence-date extraction (timeline sufficiency also reads evidence
filenames/snippets, not full extraction, so this module is currently only
used by sop_adequacy_engine.py).
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("engines.text_extraction")


def extract_text(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix == ".docx":
        return _extract_docx(file_path)
    if suffix == ".pdf":
        return _extract_pdf(file_path)
    if suffix == ".txt":
        return file_path.read_text(encoding="utf-8", errors="replace")
    raise ValueError(f"Unsupported document type '{suffix}'. Use .docx, .pdf, or .txt.")


def _extract_docx(file_path: Path) -> str:
    import docx

    document = docx.Document(str(file_path))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
            if row_text:
                parts.append(row_text)
    return "\n".join(parts)


def _extract_pdf(file_path: Path) -> str:
    import pdfplumber

    parts = []
    with pdfplumber.open(str(file_path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                parts.append(text)
    return "\n".join(parts)
