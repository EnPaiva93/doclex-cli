from __future__ import annotations

from pathlib import Path

from kreuzberg import ExtractionConfig, LayoutDetectionConfig, OutputFormat, ResultFormat, extract_file_sync
from kreuzberg.exceptions import KreuzbergError

from docsearch.metadata.models import ExtractedDoc


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
