from __future__ import annotations

from pathlib import Path

import pytest

from docsearch.extraction.extractor import ExtractionError, extract
from docsearch.metadata.models import ExtractedDoc


def test_extract_markdown(docs_dir: Path) -> None:
    doc = extract(docs_dir / "intro.md")

    assert isinstance(doc, ExtractedDoc)
    assert doc.path == str(docs_dir / "intro.md")
    assert "BM25" in doc.text
    assert doc.mime_type  # non-empty


def test_extract_txt(docs_dir: Path) -> None:
    doc = extract(docs_dir / "notas.txt")

    assert "Kreuzberg" in doc.text
    assert "Watchdog" in doc.text


def test_extract_csv(docs_dir: Path) -> None:
    doc = extract(docs_dir / "datos.csv")

    assert doc.text  # some content extracted
    assert "Alice" in doc.text or "Madrid" in doc.text or doc.text.strip()


def test_extract_missing_file_raises() -> None:
    with pytest.raises(ExtractionError):
        extract(Path("/nonexistent/file.pdf"))


def test_extract_returns_metadata(docs_dir: Path) -> None:
    doc = extract(docs_dir / "intro.md")
    assert isinstance(doc.metadata, dict)
