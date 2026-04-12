from __future__ import annotations

from pathlib import Path

from kreuzberg import ExtractionConfig, extract_file_sync
from kreuzberg.exceptions import KreuzbergError

from docsearch.metadata.models import ExtractedDoc


def extract(path: Path, *, ocr: bool = False) -> ExtractedDoc:
    """Extract text from a file using Kreuzberg.

    Args:
        ocr: Enable OCR for scanned PDFs (uses RT-DETR v2). Slower and heavier.

    Raises:
        ExtractionError: if Kreuzberg fails to extract the file.
    """
    config = ExtractionConfig(disable_ocr=not ocr)
    try:
        result = extract_file_sync(str(path), None, config)
    except (KreuzbergError, OSError) as exc:
        raise ExtractionError(str(path), str(exc)) from exc

    return ExtractedDoc(
        path=str(path),
        text=result.content or "",
        mime_type=result.mime_type or _mime_from_suffix(path),
        metadata=dict(result.metadata) if result.metadata else {},
    )


def _mime_from_suffix(path: Path) -> str:
    mapping = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".csv": "text/csv",
        ".txt": "text/plain",
        ".md": "text/markdown",
    }
    return mapping.get(path.suffix.lower(), "application/octet-stream")


class ExtractionError(Exception):
    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"Failed to extract {path!r}: {reason}")
        self.path = path
        self.reason = reason
