from __future__ import annotations

from pathlib import Path

import pytest

from doclex.metadata.db import Database
from doclex.metadata.models import FileRecord, Segment


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture()
async def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    await database.connect()
    yield database
    await database.close()


def _file(path: str = "/docs/file.txt", status: str = "pending") -> FileRecord:
    return FileRecord(
        path=path,
        hash="abc123def456",
        mtime=1700000000.0,
        size=512,
        mime_type="text/plain",
        status=status,
    )


def _seg(seg_id: str, file_path: str = "/docs/file.txt", index: int = 0) -> Segment:
    return Segment(
        id=seg_id,
        file_path=file_path,
        content=f"Contenido del segmento {seg_id} con texto suficiente para indexar.",
        location_type="block",
        location_label=f"Block {index + 1}",
        location_index=index,
    )


# ------------------------------------------------------------------
# Files — upsert
# ------------------------------------------------------------------

async def test_upsert_file_returns_positive_id(db: Database) -> None:
    file_id = await db.upsert_file(_file())
    assert isinstance(file_id, int)
    assert file_id > 0


async def test_upsert_file_is_idempotent(db: Database) -> None:
    rec = _file()
    id1 = await db.upsert_file(rec)
    id2 = await db.upsert_file(rec)
    assert id1 == id2


async def test_upsert_file_updates_on_conflict(db: Database) -> None:
    rec = _file()
    id1 = await db.upsert_file(rec)

    rec.hash = "newhash999"
    rec.status = "indexed"
    id2 = await db.upsert_file(rec)

    assert id1 == id2
    retrieved = await db.get_file_by_path(rec.path)
    assert retrieved.hash == "newhash999"
    assert retrieved.status == "indexed"


# ------------------------------------------------------------------
# Files — get
# ------------------------------------------------------------------

async def test_get_file_by_path_returns_none_for_unknown(db: Database) -> None:
    assert await db.get_file_by_path("/nonexistent.txt") is None


async def test_get_file_by_path_returns_correct_record(db: Database) -> None:
    rec = _file("/docs/nota.md")
    await db.upsert_file(rec)

    result = await db.get_file_by_path("/docs/nota.md")
    assert result is not None
    assert result.path == "/docs/nota.md"
    assert result.hash == rec.hash
    assert result.status == "pending"


async def test_get_all_files_empty(db: Database) -> None:
    assert await db.get_all_files() == []


async def test_get_all_files_ordered_by_path(db: Database) -> None:
    for name in ("c.txt", "a.txt", "b.txt"):
        await db.upsert_file(_file(f"/docs/{name}"))

    files = await db.get_all_files()
    paths = [f.path for f in files]
    assert paths == sorted(paths)


# ------------------------------------------------------------------
# Files — status transitions
# ------------------------------------------------------------------

async def test_mark_file_indexed_sets_status(db: Database) -> None:
    file_id = await db.upsert_file(_file())
    await db.mark_file_indexed(file_id)

    result = await db.get_file_by_path("/docs/file.txt")
    assert result.status == "indexed"
    assert result.indexed_at is not None
    assert result.error_msg is None


async def test_mark_file_error_sets_status_and_message(db: Database) -> None:
    file_id = await db.upsert_file(_file())
    await db.mark_file_error(file_id, "Extraction failed: unsupported format")

    result = await db.get_file_by_path("/docs/file.txt")
    assert result.status == "error"
    assert "Extraction failed" in result.error_msg


async def test_mark_indexed_clears_previous_error(db: Database) -> None:
    file_id = await db.upsert_file(_file())
    await db.mark_file_error(file_id, "some error")
    await db.mark_file_indexed(file_id)

    result = await db.get_file_by_path("/docs/file.txt")
    assert result.status == "indexed"
    assert result.error_msg is None


# ------------------------------------------------------------------
# Files — delete
# ------------------------------------------------------------------

async def test_delete_file_removes_record(db: Database) -> None:
    await db.upsert_file(_file("/docs/borrar.txt"))
    await db.delete_file("/docs/borrar.txt")

    assert await db.get_file_by_path("/docs/borrar.txt") is None


async def test_delete_file_nonexistent_is_noop(db: Database) -> None:
    await db.delete_file("/nonexistent.txt")  # must not raise


async def test_delete_file_cascades_to_segments(db: Database) -> None:
    file_id = await db.upsert_file(_file("/docs/cascade.txt"))
    segs = [_seg(f"seg{i}", file_path="/docs/cascade.txt", index=i) for i in range(3)]
    await db.insert_segments(file_id, segs)

    await db.delete_file("/docs/cascade.txt")

    all_segs = await db.get_all_segments()
    seg_ids = {s.id for s in all_segs}
    assert not seg_ids.intersection({"seg0", "seg1", "seg2"})


# ------------------------------------------------------------------
# Segments — insert / get
# ------------------------------------------------------------------

async def test_insert_and_get_segments(db: Database) -> None:
    file_id = await db.upsert_file(_file())
    segs = [_seg(f"seg{i}", index=i) for i in range(3)]
    await db.insert_segments(file_id, segs)

    result = await db.get_segments_for_file(file_id)
    assert len(result) == 3
    ids = {s.id for s in result}
    assert ids == {"seg0", "seg1", "seg2"}


async def test_get_segments_ordered_by_location_index(db: Database) -> None:
    file_id = await db.upsert_file(_file())
    segs = [_seg(f"seg{i}", index=i) for i in range(5)]
    await db.insert_segments(file_id, segs)

    result = await db.get_segments_for_file(file_id)
    indices = [s.location_index for s in result]
    assert indices == sorted(indices)


async def test_get_segments_for_file_returns_empty_when_none(db: Database) -> None:
    file_id = await db.upsert_file(_file())
    assert await db.get_segments_for_file(file_id) == []


async def test_get_segment_by_id_returns_none_for_unknown(db: Database) -> None:
    assert await db.get_segment_by_id("nonexistent_id") is None


async def test_get_segment_by_id_returns_correct_segment(db: Database) -> None:
    rec = _file()
    file_id = await db.upsert_file(rec)
    await db.insert_segments(file_id, [_seg("target_seg")])

    result = await db.get_segment_by_id("target_seg")
    assert result is not None
    assert result.id == "target_seg"
    assert result.file_path == rec.path


# ------------------------------------------------------------------
# Segments — bm25_doc_id
# ------------------------------------------------------------------

async def test_get_bm25_doc_ids_for_file(db: Database) -> None:
    file_id = await db.upsert_file(_file())
    segs = [_seg(f"seg{i}", index=i) for i in range(3)]
    for i, seg in enumerate(segs):
        seg.bm25_doc_id = i + 100
    await db.insert_segments(file_id, segs)

    ids = await db.get_bm25_doc_ids_for_file(file_id)
    assert sorted(ids) == [100, 101, 102]


async def test_get_bm25_doc_ids_excludes_nulls(db: Database) -> None:
    file_id = await db.upsert_file(_file())
    seg = _seg("seg_no_bm25")
    seg.bm25_doc_id = None
    await db.insert_segments(file_id, [seg])

    assert await db.get_bm25_doc_ids_for_file(file_id) == []


async def test_update_bm25_doc_ids(db: Database) -> None:
    file_id = await db.upsert_file(_file())
    segs = [_seg(f"seg{i}", index=i) for i in range(3)]
    await db.insert_segments(file_id, segs)

    await db.update_bm25_doc_ids(segs, [10, 20, 30])

    ids = await db.get_bm25_doc_ids_for_file(file_id)
    assert sorted(ids) == [10, 20, 30]


# ------------------------------------------------------------------
# Segments — delete
# ------------------------------------------------------------------

async def test_delete_segments_for_file_removes_all(db: Database) -> None:
    file_id = await db.upsert_file(_file())
    await db.insert_segments(file_id, [_seg(f"seg{i}", index=i) for i in range(3)])

    await db.delete_segments_for_file(file_id)

    assert await db.get_segments_for_file(file_id) == []


async def test_delete_segments_does_not_affect_other_files(db: Database) -> None:
    id_a = await db.upsert_file(_file("/docs/a.txt"))
    id_b = await db.upsert_file(_file("/docs/b.txt"))

    await db.insert_segments(id_a, [_seg("seg_a", file_path="/docs/a.txt")])
    await db.insert_segments(id_b, [_seg("seg_b", file_path="/docs/b.txt")])

    await db.delete_segments_for_file(id_a)

    remaining = await db.get_segments_for_file(id_b)
    assert len(remaining) == 1
    assert remaining[0].id == "seg_b"


# ------------------------------------------------------------------
# get_all_segments
# ------------------------------------------------------------------

async def test_get_all_segments_returns_all_with_file_path(db: Database) -> None:
    file_id = await db.upsert_file(_file())
    segs = [_seg(f"seg{i}", index=i) for i in range(4)]
    await db.insert_segments(file_id, segs)

    all_segs = await db.get_all_segments()
    assert len(all_segs) == 4
    assert all(s.file_path == "/docs/file.txt" for s in all_segs)


async def test_get_all_segments_empty_when_no_files(db: Database) -> None:
    assert await db.get_all_segments() == []
