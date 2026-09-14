from __future__ import annotations

from pathlib import Path

from doclex.index.title_index import TitleIndex, fingerprint
from doclex.metadata.models import FileRecord


def _file(file_id: int, path: str) -> FileRecord:
    return FileRecord(
        id=file_id, path=path, hash="h", mtime=0.0, size=1,
        mime_type="application/pdf", status="indexed",
    )


def test_stored_index_is_reused(tmp_path: Path) -> None:
    files = [_file(1, "/docs/vacaciones.pdf"), _file(2, "/docs/sueldos.pdf")]
    mark = fingerprint(files)

    built = TitleIndex(tmp_path / "titles")
    built.build(files)
    built.save(mark)

    loaded = TitleIndex(tmp_path / "titles")
    assert loaded.load(mark) is True
    assert loaded.search("vacaciones", 5).get(1, 0) > 0


def test_stored_index_is_rejected_when_files_changed(tmp_path: Path) -> None:
    """A title index built from a different file set must never be reused."""
    original = [_file(1, "/docs/vacaciones.pdf")]
    built = TitleIndex(tmp_path / "titles")
    built.build(original)
    built.save(fingerprint(original))

    grown = original + [_file(2, "/docs/nuevo.pdf")]

    assert TitleIndex(tmp_path / "titles").load(fingerprint(grown)) is False


def test_missing_index_reports_absent(tmp_path: Path) -> None:
    assert TitleIndex(tmp_path / "nada").load("cualquiera") is False


def test_corrupt_metadata_is_treated_as_absent(tmp_path: Path) -> None:
    index_dir = tmp_path / "titles"
    index_dir.mkdir()
    (index_dir / "titles.json").write_text("{ no es json", encoding="utf-8")

    assert TitleIndex(index_dir).load("cualquiera") is False


def test_fingerprint_ignores_file_order() -> None:
    a, b = _file(1, "/docs/a.pdf"), _file(2, "/docs/b.pdf")

    assert fingerprint([a, b]) == fingerprint([b, a])
