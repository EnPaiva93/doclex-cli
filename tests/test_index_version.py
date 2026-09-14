from __future__ import annotations

from pathlib import Path

import pytest

from doclex.metadata.db import INDEX_VERSION, Database


@pytest.fixture()
async def db(tmp_path: Path):
    database = Database(tmp_path / "doclex.db")
    await database.connect()
    yield database
    await database.close()


async def test_empty_corpus_has_no_version(db: Database) -> None:
    """Nothing indexed yet is not the same as indexed by an old version."""
    assert await db.index_version() is None


async def test_version_round_trips(db: Database) -> None:
    await db.set_index_version()

    assert await db.index_version() == INDEX_VERSION


async def test_segments_without_a_version_are_treated_as_v1(db: Database) -> None:
    """Corpora indexed before versioning existed still hold v1 segments."""
    await db.conn.execute(
        "INSERT INTO files (path, hash, mtime, size, mime_type, status) "
        "VALUES ('/docs/a.pdf', 'h', 0, 1, 'application/pdf', 'indexed')"
    )
    await db.conn.execute(
        "INSERT INTO segments (id, file_id, content, location_type, location_label, "
        "location_index, char_count) VALUES ('s1', 1, 'texto', 'block', 'Block 1', 0, 5)"
    )
    await db.conn.commit()

    assert await db.index_version() == 1


async def test_setting_the_version_twice_keeps_one_row(db: Database) -> None:
    await db.set_index_version()
    await db.set_index_version()

    assert await db.index_version() == INDEX_VERSION
