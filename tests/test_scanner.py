from __future__ import annotations

from pathlib import Path

import pytest

from docsearch.ingestion.scanner import file_hash, file_record_from_disk, reconcile
from docsearch.metadata.db import Database
from docsearch.metadata.models import FileRecord


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture()
async def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    await database.connect()
    yield database
    await database.close()


# ------------------------------------------------------------------
# file_hash
# ------------------------------------------------------------------

def test_file_hash_is_consistent(tmp_path: Path) -> None:
    f = tmp_path / "doc.txt"
    f.write_text("hola mundo", encoding="utf-8")
    assert file_hash(f) == file_hash(f)


def test_file_hash_differs_for_different_content(tmp_path: Path) -> None:
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("contenido uno", encoding="utf-8")
    f2.write_text("contenido dos", encoding="utf-8")
    assert file_hash(f1) != file_hash(f2)


def test_file_hash_is_64_char_hex(tmp_path: Path) -> None:
    f = tmp_path / "doc.bin"
    f.write_bytes(b"\x00\x01\x02\xff")
    h = file_hash(f)
    assert len(h) == 64
    int(h, 16)  # raises if not valid hex


# ------------------------------------------------------------------
# file_record_from_disk
# ------------------------------------------------------------------

def test_file_record_from_disk_fields(tmp_path: Path) -> None:
    f = tmp_path / "nota.txt"
    f.write_text("contenido de prueba", encoding="utf-8")
    stat = f.stat()
    rec = file_record_from_disk(f)

    assert rec.path == str(f)
    assert rec.status == "pending"
    assert rec.size == stat.st_size
    assert rec.mtime == stat.st_mtime
    assert rec.mime_type == "text/plain"
    assert len(rec.hash) == 64


def test_file_record_from_disk_mime_types(tmp_path: Path) -> None:
    cases = {
        "doc.pdf": "application/pdf",
        "doc.md": "text/markdown",
        "doc.csv": "text/csv",
        "doc.txt": "text/plain",
        "doc.docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc.xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    for filename, expected_mime in cases.items():
        f = tmp_path / filename
        f.write_bytes(b"dummy")
        assert file_record_from_disk(f).mime_type == expected_mime, f"Wrong mime for {filename}"


# ------------------------------------------------------------------
# reconcile
# ------------------------------------------------------------------

async def test_reconcile_detects_new_files(tmp_path: Path, db: Database) -> None:
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "nuevo.md").write_text("# Hola\n\nContenido nuevo.", encoding="utf-8")

    changes = await reconcile(folder, db)

    assert len(changes.new) == 1
    assert changes.new[0].name == "nuevo.md"
    assert changes.modified == []
    assert changes.deleted == []


async def test_reconcile_detects_deleted_files(tmp_path: Path, db: Database) -> None:
    folder = tmp_path / "docs"
    folder.mkdir()

    # Register a file in DB that no longer exists on disk
    await db.upsert_file(FileRecord(
        path=str(folder / "ghost.txt"),
        hash="abc123",
        mtime=0.0,
        size=100,
        mime_type="text/plain",
        status="indexed",
    ))

    changes = await reconcile(folder, db)

    assert str(folder / "ghost.txt") in changes.deleted
    assert changes.new == []
    assert changes.modified == []


async def test_reconcile_detects_modified_files(tmp_path: Path, db: Database) -> None:
    folder = tmp_path / "docs"
    folder.mkdir()
    f = folder / "doc.txt"
    f.write_text("versión original", encoding="utf-8")

    stat = f.stat()
    # Store a stale record: older mtime triggers hash recheck, hash mismatch → modified
    await db.upsert_file(FileRecord(
        path=str(f),
        hash="hash_antiguo_diferente",
        mtime=stat.st_mtime - 10,
        size=stat.st_size,
        mime_type="text/plain",
        status="indexed",
    ))

    changes = await reconcile(folder, db)

    assert f in changes.modified
    assert changes.new == []
    assert changes.deleted == []


async def test_reconcile_no_changes_when_file_unchanged(tmp_path: Path, db: Database) -> None:
    folder = tmp_path / "docs"
    folder.mkdir()
    f = folder / "doc.txt"
    f.write_text("sin cambios", encoding="utf-8")

    stat = f.stat()
    await db.upsert_file(FileRecord(
        path=str(f),
        hash=file_hash(f),
        mtime=stat.st_mtime,
        size=stat.st_size,
        mime_type="text/plain",
        status="indexed",
    ))

    changes = await reconcile(folder, db)

    assert changes.new == []
    assert changes.modified == []
    assert changes.deleted == []


async def test_reconcile_ignores_docsearch_dir(tmp_path: Path, db: Database) -> None:
    folder = tmp_path / "docs"
    folder.mkdir()
    docsearch_dir = folder / ".docsearch"
    docsearch_dir.mkdir()
    (docsearch_dir / "internal.md").write_text("# Internal cache", encoding="utf-8")

    changes = await reconcile(folder, db)

    assert changes.new == []


async def test_reconcile_ignores_unsupported_extensions(tmp_path: Path, db: Database) -> None:
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "imagen.png").write_bytes(b"\x89PNG")
    (folder / "script.py").write_text("print('hi')", encoding="utf-8")
    (folder / "archive.zip").write_bytes(b"PK")

    changes = await reconcile(folder, db)

    assert changes.new == []


async def test_reconcile_empty_folder(tmp_path: Path, db: Database) -> None:
    folder = tmp_path / "empty"
    folder.mkdir()

    changes = await reconcile(folder, db)

    assert changes.new == []
    assert changes.modified == []
    assert changes.deleted == []


async def test_reconcile_multiple_file_types(tmp_path: Path, db: Database) -> None:
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "doc.md").write_text("# Markdown", encoding="utf-8")
    (folder / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (folder / "notes.txt").write_text("Notas de texto.", encoding="utf-8")

    changes = await reconcile(folder, db)

    assert len(changes.new) == 3
    names = {p.name for p in changes.new}
    assert names == {"doc.md", "data.csv", "notes.txt"}
