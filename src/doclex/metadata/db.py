from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite

from .models import FileRecord, Segment

# Bumped whenever segmentation changes shape, since stored segments then no
# longer match what the current code would produce. Version 2 moved PDFs from
# 1024-character chunks to whole pages.
INDEX_VERSION = 2

if TYPE_CHECKING:
    pass

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT    NOT NULL UNIQUE,
    hash        TEXT    NOT NULL,
    mtime       REAL    NOT NULL,
    size        INTEGER NOT NULL,
    mime_type   TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'pending',
    indexed_at  REAL,
    error_msg   TEXT
);

CREATE TABLE IF NOT EXISTS segments (
    id              TEXT    PRIMARY KEY,
    file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    content         TEXT    NOT NULL,
    location_type   TEXT    NOT NULL,
    location_label  TEXT    NOT NULL,
    location_index  INTEGER NOT NULL,
    char_count      INTEGER NOT NULL,
    bm25_doc_id     INTEGER
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_files_path   ON files(path);
CREATE INDEX IF NOT EXISTS idx_files_hash   ON files(hash);
CREATE INDEX IF NOT EXISTS idx_segs_file_id ON segments(file_id);
"""


class Database:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    async def upsert_file(self, record: FileRecord) -> int:
        """Insert or update a file record. Returns the file id."""
        async with self.conn.execute(
            """
            INSERT INTO files (path, hash, mtime, size, mime_type, status, indexed_at, error_msg)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                hash       = excluded.hash,
                mtime      = excluded.mtime,
                size       = excluded.size,
                mime_type  = excluded.mime_type,
                status     = excluded.status,
                indexed_at = excluded.indexed_at,
                error_msg  = excluded.error_msg
            """,
            (
                record.path,
                record.hash,
                record.mtime,
                record.size,
                record.mime_type,
                record.status,
                record.indexed_at,
                record.error_msg,
            ),
        ) as cursor:
            await self.conn.commit()
            # Fetch id after upsert
            async with self.conn.execute(
                "SELECT id FROM files WHERE path = ?", (record.path,)
            ) as cur2:
                row = await cur2.fetchone()
                return row["id"]

    async def get_file_by_path(self, path: str) -> FileRecord | None:
        async with self.conn.execute(
            "SELECT * FROM files WHERE path = ?", (path,)
        ) as cursor:
            row = await cursor.fetchone()
            return _row_to_file(row) if row else None

    async def get_all_files(self) -> list[FileRecord]:
        async with self.conn.execute("SELECT * FROM files ORDER BY path") as cursor:
            rows = await cursor.fetchall()
            return [_row_to_file(r) for r in rows]

    async def mark_file_indexed(self, file_id: int) -> None:
        await self.conn.execute(
            "UPDATE files SET status = 'indexed', indexed_at = ?, error_msg = NULL WHERE id = ?",
            (time.time(), file_id),
        )
        await self.conn.commit()

    async def mark_file_error(self, file_id: int, error_msg: str) -> None:
        await self.conn.execute(
            "UPDATE files SET status = 'error', error_msg = ? WHERE id = ?",
            (error_msg, file_id),
        )
        await self.conn.commit()

    async def delete_file(self, path: str) -> None:
        """Deletes file and cascades to its segments."""
        await self.conn.execute("DELETE FROM files WHERE path = ?", (path,))
        await self.conn.commit()

    # ------------------------------------------------------------------
    # Segments
    # ------------------------------------------------------------------

    async def insert_segments(self, file_id: int, segments: list[Segment]) -> None:
        await self.conn.executemany(
            """
            INSERT OR REPLACE INTO segments
                (id, file_id, content, location_type, location_label, location_index, char_count, bm25_doc_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    s.id,
                    file_id,
                    s.content,
                    s.location_type,
                    s.location_label,
                    s.location_index,
                    s.char_count,
                    s.bm25_doc_id,
                )
                for s in segments
            ],
        )
        await self.conn.commit()

    async def get_segments_for_file(self, file_id: int) -> list[Segment]:
        async with self.conn.execute(
            """
            SELECT s.*, f.path as file_path FROM segments s
            JOIN files f ON f.id = s.file_id
            WHERE s.file_id = ?
            ORDER BY s.location_index
            """,
            (file_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_segment(r) for r in rows]

    async def get_segment_by_id(self, segment_id: str) -> Segment | None:
        async with self.conn.execute(
            """
            SELECT s.*, f.path as file_path FROM segments s
            JOIN files f ON f.id = s.file_id
            WHERE s.id = ?
            """,
            (segment_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return _row_to_segment(row) if row else None

    async def get_bm25_doc_ids_for_file(self, file_id: int) -> list[int]:
        async with self.conn.execute(
            "SELECT bm25_doc_id FROM segments WHERE file_id = ? AND bm25_doc_id IS NOT NULL",
            (file_id,),
        ) as cursor:
            rows = await cursor.fetchall()
            return [r["bm25_doc_id"] for r in rows]

    async def delete_segments_for_file(self, file_id: int) -> None:
        await self.conn.execute("DELETE FROM segments WHERE file_id = ?", (file_id,))
        await self.conn.commit()

    async def update_bm25_doc_ids(self, segments: list, doc_ids: list[int]) -> None:
        """Update bm25_doc_id for each segment after an index rebuild."""
        await self.conn.executemany(
            "UPDATE segments SET bm25_doc_id = ? WHERE id = ?",
            [(doc_id, seg.id) for seg, doc_id in zip(segments, doc_ids)],
        )
        await self.conn.commit()

    async def get_segments_by_bm25_ids(
        self, doc_ids: list[int]
    ) -> dict[int, tuple[Segment, int, str]]:
        """Batch-resolve BM25 doc ids to segments, with owning file id and mime type.

        One query for a whole result page — the search path must never load the
        full corpus just to map ids back to segments.
        """
        if not doc_ids:
            return {}
        placeholders = ",".join("?" * len(doc_ids))
        async with self.conn.execute(
            f"""
            SELECT s.*, f.path AS file_path, f.id AS owner_id, f.mime_type AS mime_type
            FROM segments s
            JOIN files f ON f.id = s.file_id
            WHERE s.bm25_doc_id IN ({placeholders})
            """,
            doc_ids,
        ) as cursor:
            rows = await cursor.fetchall()
        return {
            r["bm25_doc_id"]: (_row_to_segment(r), r["owner_id"], r["mime_type"])
            for r in rows
        }

    async def index_version(self) -> int | None:
        """Version of the segments already stored, or None for an empty corpus."""
        async with self.conn.execute(
            "SELECT value FROM meta WHERE key = 'index_version'"
        ) as cursor:
            row = await cursor.fetchone()
        if row:
            return int(row["value"])
        # A corpus indexed before versioning existed still holds v1 segments.
        async with self.conn.execute("SELECT COUNT(*) AS n FROM segments") as cursor:
            existing = await cursor.fetchone()
        return 1 if existing and existing["n"] else None

    async def set_index_version(self, version: int = INDEX_VERSION) -> None:
        await self.conn.execute(
            "INSERT INTO meta (key, value) VALUES ('index_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(version),),
        )
        await self.conn.commit()

    async def get_char_counts_by_file(self) -> dict[int, int]:
        """Total extracted characters per file id, zero-filled for files with none."""
        async with self.conn.execute(
            """
            SELECT f.id AS file_id, COALESCE(SUM(s.char_count), 0) AS chars
            FROM files f
            LEFT JOIN segments s ON s.file_id = f.id
            GROUP BY f.id
            """
        ) as cursor:
            rows = await cursor.fetchall()
        return {r["file_id"]: r["chars"] for r in rows}

    async def get_all_segments(self) -> list[Segment]:
        """Used to rebuild the BM25 index on startup."""
        async with self.conn.execute(
            """
            SELECT s.*, f.path as file_path FROM segments s
            JOIN files f ON f.id = s.file_id
            ORDER BY s.bm25_doc_id
            """
        ) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_segment(r) for r in rows]


# ------------------------------------------------------------------
# Row helpers
# ------------------------------------------------------------------

def _row_to_file(row: aiosqlite.Row) -> FileRecord:
    return FileRecord(
        id=row["id"],
        path=row["path"],
        hash=row["hash"],
        mtime=row["mtime"],
        size=row["size"],
        mime_type=row["mime_type"],
        status=row["status"],
        indexed_at=row["indexed_at"],
        error_msg=row["error_msg"],
    )


def _row_to_segment(row: aiosqlite.Row) -> Segment:
    return Segment(
        id=row["id"],
        file_path=row["file_path"],
        content=row["content"],
        location_type=row["location_type"],
        location_label=row["location_label"],
        location_index=row["location_index"],
        char_count=row["char_count"],
        bm25_doc_id=row["bm25_doc_id"],
    )
