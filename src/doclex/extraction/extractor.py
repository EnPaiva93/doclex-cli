from __future__ import annotations

from pathlib import Path

from kreuzberg import ExtractionConfig, LayoutDetectionConfig, OutputFormat, ResultFormat, extract_file_sync
from kreuzberg.exceptions import KreuzbergError

from doclex.metadata.models import ExtractedDoc, Page


def extract(path: Path) -> ExtractedDoc:
    """Extract text from a file using Kreuzberg with layout detection (RT-DETR v2 / TATR).

    Raises:
        ExtractionError: if Kreuzberg fails to extract the file.
    """
    config = ExtractionConfig(
        layout=LayoutDetectionConfig(),
        output_format=OutputFormat.MARKDOWN,
        result_format=ResultFormat.UNIFIED,
    )

    try:
        result = extract_file_sync(str(path), None, config)
    except (KreuzbergError, OSError) as exc:
        raise ExtractionError(str(path), str(exc)) from exc
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as exc:
        # pyo3_runtime.PanicException inherits from BaseException, not Exception.
        # Catch Kreuzberg Rust panics (e.g. UTF-8 char boundary bug in markdown renderer)
        # and fall back to standard extraction so the file is not lost.
        if "char boundary" in str(exc):
            try:
                result = extract_file_sync(str(path), None, ExtractionConfig())
            except (KreuzbergError, OSError) as exc2:
                raise ExtractionError(str(path), str(exc2)) from exc2
        else:
            raise ExtractionError(str(path), str(exc)) from exc

    tables = list(result.tables) if result.tables else []

    metadata = dict(result.metadata) if result.metadata else {}
    if "pages" in metadata and isinstance(metadata["pages"], dict):
        metadata["pages"].pop("boundaries", None)

    return ExtractedDoc(
        path=str(path),
        text=result.content or "",
        mime_type=result.mime_type or _mime_from_suffix(path),
        metadata=metadata,
        tables=tables,
        pages=_pages(result),
    )


def _pages(result: object) -> list[Page]:
    """Collect per-page text, which is what lets a result cite a page number.

    Kreuzberg reports pages separately from the unified content; the unified
    markdown carries no page boundaries at all, so without this the page a
    passage came from is unrecoverable.
    """
    raw = getattr(result, "pages", None) or []
    pages: list[Page] = []
    for i, page in enumerate(raw, 1):
        if not isinstance(page, dict):
            continue
        content = page.get("content") or ""
        if content.strip():
            pages.append(Page(number=int(page.get("page_number") or i), content=content))
    return pages


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
