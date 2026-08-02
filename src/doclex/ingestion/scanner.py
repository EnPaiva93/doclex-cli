from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from doclex.config import SUPPORTED_EXTENSIONS
from doclex.metadata.db import Database
from doclex.metadata.models import FileRecord


@dataclass
class ChangeSet:
    new: list[Path]
    modified: list[Path]
    deleted: list[str]  # paths of files no longer on disk


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def file_record_from_disk(path: Path) -> FileRecord:
    stat = path.stat()
    return FileRecord(
        path=str(path),
        hash=file_hash(path),
        mtime=stat.st_mtime,
        size=stat.st_size,
        mime_type=_mime_from_suffix(path),
        status="pending",
    )


async def reconcile(folder: Path, db: Database) -> ChangeSet:
    """Compare files on disk against SQLite state and return what changed."""
    # Files on disk
    on_disk: dict[str, Path] = {}
    for path in folder.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            # Skip the .doclex directory itself
            if ".doclex" in path.parts:
                continue
            on_disk[str(path)] = path

    # Files in SQLite
    db_records: dict[str, FileRecord] = {
        r.path: r for r in await db.get_all_files()
    }

    new: list[Path] = []
    modified: list[Path] = []
    deleted: list[str] = []

    for path_str, path in on_disk.items():
        if path_str not in db_records:
            new.append(path)
        else:
            db_rec = db_records[path_str]
            stat = path.stat()
            # Use mtime as cheap pre-check before computing hash
            if stat.st_mtime != db_rec.mtime or stat.st_size != db_rec.size:
                current_hash = file_hash(path)
                if current_hash != db_rec.hash:
                    modified.append(path)

    for path_str in db_records:
        if path_str not in on_disk:
            deleted.append(path_str)

    return ChangeSet(new=new, modified=modified, deleted=deleted)


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
