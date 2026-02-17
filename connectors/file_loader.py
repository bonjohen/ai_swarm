"""Load local files — text, markdown, JSON, and basic PDF text extraction."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".html", ".htm"}


@dataclass
class FileContent:
    path: str
    filename: str
    extension: str
    text: str
    content_hash: str
    meta: dict


def load_file(path: str | Path) -> FileContent:
    """Load a local file and return its text content."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    ext = path.suffix.lower()
    filename = path.name

    if ext == ".json":
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        text = json.dumps(data, indent=2)
    elif ext == ".pdf":
        text = _extract_pdf_text(path)
    elif ext in SUPPORTED_TEXT_EXTENSIONS or ext == "":
        text = path.read_text(encoding="utf-8")
    else:
        text = path.read_text(encoding="utf-8", errors="replace")

    content_hash = hashlib.sha256(text.encode()).hexdigest()
    return FileContent(
        path=str(path),
        filename=filename,
        extension=ext,
        text=text,
        content_hash=content_hash,
        meta={"size_bytes": path.stat().st_size},
    )


def _extract_pdf_text(path: Path) -> str:
    """Extract text from PDF. Uses PyMuPDF if available, otherwise falls back to basic read."""
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(str(path))
        pages = [page.get_text() for page in doc]
        doc.close()
        return "\n\n".join(pages)
    except ImportError:
        logger.warning("PyMuPDF not installed — reading PDF as raw text (install pymupdf for proper extraction)")
        return path.read_bytes().decode("utf-8", errors="replace")
