from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Awaitable

from docsearch.cache.store import CacheStore
from docsearch.config import Config
from docsearch.extraction.extractor import ExtractionError, extract
from docsearch.index.bm25_index import BM25Index, make_snippet
from docsearch.ingestion.scanner import ChangeSet, file_hash, file_record_from_disk, reconcile
from docsearch.ingestion.watcher import FileWatcher
from docsearch.metadata.db import Database
from docsearch.metadata.models import FileRecord, SearchResult
from docsearch.segmentation.segmenter import segment


class Pipeline:
    """Orchestrates extraction → segmentation → index → metadata."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._db = Database(config.db_path)
        self._cache = CacheStore(config.cache_dir)
        self._index = BM25Index(config.bm25_index_dir)
        self._watcher: FileWatcher | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def startup(self) -> None:
        await self._db.connect()
        await self._load_or_rebuild_index()

    async def shutdown(self) -> None:
        self._index.save()
        await self._db.close()

    async def _load_or_rebuild_index(self) -> None:
        if self._config.bm25_index_dir.exists() and any(self._config.bm25_index_dir.iterdir()):
            self._index.load_or_create()
        else:
            segments = await self._db.get_all_segments()
            if segments:
                self._index.rebuild_from_segments(segments)
            else:
                self._index.load_or_create()

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------

    async def reconcile(self) -> ChangeSet:
        return await reconcile(self._config.folder, self._db)

    async def apply_changes(
        self,
        changes: ChangeSet,
        on_progress: Callable[[Path, str], None] | None = None,
    ) -> None:
        for path in changes.new:
            if on_progress:
                on_progress(path, "indexing")
            await self._process_file(path)

        for path in changes.modified:
            if on_progress:
                on_progress(path, "updating")
            await self._remove_file(str(path))
            await self._process_file(path)

        for path_str in changes.deleted:
            if on_progress:
                on_progress(Path(path_str), "removing")
            await self._remove_file(path_str)

    # ------------------------------------------------------------------
    # File processing
    # ------------------------------------------------------------------

    async def _process_file(self, path: Path) -> None:
        record = file_record_from_disk(path)
        file_id = await self._db.upsert_file(record)

        try:
            doc = extract(path)
            segments = segment(doc)

            if not segments:
                await self._db.mark_file_indexed(file_id)
                return

            doc_ids = self._index.add(segments)
            for seg, doc_id in zip(segments, doc_ids):
                seg.bm25_doc_id = doc_id

            await self._db.insert_segments(file_id, segments)
            self._cache.put(doc, segments)
            await self._db.mark_file_indexed(file_id)

        except ExtractionError as exc:
            await self._db.mark_file_error(file_id, str(exc))

    async def _remove_file(self, path_str: str) -> None:
        record = await self._db.get_file_by_path(path_str)
        if record and record.id is not None:
            bm25_ids = await self._db.get_bm25_doc_ids_for_file(record.id)
            self._index.delete(bm25_ids)
            await self._db.delete_file(path_str)
        self._cache.delete(path_str)

    # ------------------------------------------------------------------
    # Public commands
    # ------------------------------------------------------------------

    async def reindex_file(self, path: Path) -> None:
        await self._remove_file(str(path))
        await self._process_file(path)
        self._index.save()

    async def reindex_all(
        self,
        on_progress: Callable[[Path, str], None] | None = None,
    ) -> None:
        """Force re-extraction and re-indexing of every file currently in the corpus."""
        files = await self._db.get_all_files()
        for rec in files:
            path = Path(rec.path)
            if not path.exists():
                continue
            if on_progress:
                on_progress(path, "reindexing")
            await self._remove_file(str(path))
            await self._process_file(path)
        self._index.save()

    async def search(self, query: str, top_k: int | None = None) -> list[SearchResult]:
        k = top_k or self._config.top_k
        query = query.strip()
        if not query:
            return []

        hits = self._index.search(query, k)
        if not hits:
            return []

        # Map bm25_doc_id → segment via DB
        # We fetch all segments to build the id map (cheap, in-memory)
        all_segments = await self._db.get_all_segments()
        id_map: dict[int, object] = {
            s.bm25_doc_id: s for s in all_segments if s.bm25_doc_id is not None
        }

        results: list[SearchResult] = []
        for doc_id, score in hits:
            seg = id_map.get(doc_id)
            if seg is None:
                continue
            file_rec = await self._db.get_file_by_path(seg.file_path)
            results.append(
                SearchResult(
                    segment_id=seg.id,
                    score=score,
                    file_path=seg.file_path,
                    mime_type=file_rec.mime_type if file_rec else "",
                    location_type=seg.location_type,
                    location_label=seg.location_label,
                    content=seg.content,
                    snippet=make_snippet(seg.content, query),
                )
            )
        return results

    async def list_files(self, status: str | None = None) -> list[FileRecord]:
        files = await self._db.get_all_files()
        if status:
            files = [f for f in files if f.status == status]
        return files

    async def corpus_status(self) -> dict:
        files = await self._db.get_all_files()
        segments = await self._db.get_all_segments()
        # Only reconcile if there's already an index — avoids scanning large filesystems
        has_index = len(files) > 0
        changes = await reconcile(self._config.folder, self._db) if has_index else ChangeSet(new=[], modified=[], deleted=[])
        return {
            "folder": str(self._config.folder),
            "files_total": len(files),
            "files_indexed": sum(1 for f in files if f.status == "indexed"),
            "files_error": sum(1 for f in files if f.status == "error"),
            "files_pending": sum(1 for f in files if f.status == "pending"),
            "segments_total": len(segments),
            "index_size": len(self._index),
            "pending_new": len(changes.new),
            "pending_modified": len(changes.modified),
            "pending_deleted": len(changes.deleted),
            "has_index": has_index,
        }

    async def get_file_status(self, path: Path) -> dict:
        """Return detailed status of a specific file: DB record, segments, disk state."""
        record = await self._db.get_file_by_path(str(path))
        on_disk = path.exists()
        is_modified = False
        segments: list = []

        if on_disk and record:
            current_hash = file_hash(path)
            is_modified = current_hash != record.hash
        if record and record.id is not None:
            segments = await self._db.get_segments_for_file(record.id)

        return {
            "path": str(path),
            "on_disk": on_disk,
            "in_index": record is not None,
            "is_modified": is_modified,
            "record": record,
            "segments": segments,
        }

    # ------------------------------------------------------------------
    # Watcher
    # ------------------------------------------------------------------

    def start_watcher(self, loop: asyncio.AbstractEventLoop) -> None:
        self._watcher = FileWatcher(
            self._config.folder,
            self._config.debounce_secs,
            self._on_file_change,
        )
        self._watcher.start(loop)

    def stop_watcher(self) -> None:
        if self._watcher:
            self._watcher.stop()
            self._watcher = None

    def _on_file_change(self, path: Path, event_type: str) -> None:
        loop = asyncio.get_event_loop()
        if event_type == "deleted":
            loop.create_task(self._remove_file(str(path)))
        else:
            loop.create_task(self._reindex_on_change(path))

    async def _reindex_on_change(self, path: Path) -> None:
        await self._remove_file(str(path))
        if path.exists():
            await self._process_file(path)
        self._index.save()
