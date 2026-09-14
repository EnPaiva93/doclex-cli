from __future__ import annotations

from doclex.metadata.models import FileRecord
from doclex.pipeline import _lacks_text


def _record(size_kb: int, status: str = "indexed") -> FileRecord:
    return FileRecord(
        id=1, path="/docs/f.pdf", hash="h", mtime=0.0,
        size=size_kb * 1024, mime_type="application/pdf", status=status,
    )


def test_scanned_pdf_is_flagged() -> None:
    """428 KB yielding 70 characters is an image of a document, not a document."""
    assert _lacks_text(_record(428), chars=70) is True


def test_ordinary_document_is_not_flagged() -> None:
    assert _lacks_text(_record(369), chars=52985) is False


def test_short_but_genuine_document_is_not_flagged() -> None:
    """A small file with little text is still text; density is what matters."""
    assert _lacks_text(_record(62), chars=208) is False


def test_failed_extraction_is_not_reported_as_missing_text() -> None:
    """Errored files already report their own failure; do not double-count them."""
    assert _lacks_text(_record(500, status="error"), chars=0) is False


def test_pending_file_is_not_flagged() -> None:
    assert _lacks_text(_record(500, status="pending"), chars=0) is False


def test_unknown_size_is_not_flagged() -> None:
    record = _record(0)
    assert _lacks_text(record, chars=0) is False
