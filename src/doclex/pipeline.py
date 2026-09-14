from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Awaitable

from doclex.cache.store import CacheStore
from doclex.config import Config
from doclex.extraction.extractor import ExtractionError, extract
from doclex.index.bm25_index import BM25Index, make_snippet
from doclex.index.title_index import TitleIndex
from doclex.ingestion.scanner import ChangeSet, file_hash, file_record_from_disk, reconcile
from doclex.ingestion.watcher import FileWatcher
from doclex.metadata.db import Database
from doclex.metadata.models import DocumentResult, FileRecord, PassageResult
from doclex.segmentation.segmenter import segment


# Passages fetched per requested document. Grouping collapses many passages into
# one document, so the index must be asked for more candidates than final slots.
_CANDIDATE_FACTOR = 5

# Weight of each additional passage when scoring a document. The best passage
# dominates; further matches add a little, rewarding coverage without letting
# long documents win on volume alone.
_PASSAGE_WEIGHTS = (1.0, 0.25, 0.10)

# How much a file-name match counts next to a body match. Body evidence still
# leads; the title breaks ties between documents that quote the same words.
# Sweeping 0.5 to 4.0 over the sample queries moved no top result, so this is
# set conservatively rather than tuned — it wants a relevance set to pin down.
_TITLE_WEIGHT = 1.5


def _document_score(passages: list[PassageResult]) -> float:
    """Score a document from its passages, ranked best first."""
    return sum(
        p.score * w for p, w in zip(passages, _PASSAGE_WEIGHTS)
    )


class Pipeline:
    """Orchestrates extraction → segmentation → index → metadata."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._db = Database(config.db_path)
        self._cache = CacheStore(config.cache_dir)
        self._index = BM25Index(config.bm25_index_dir)
        self._titles = TitleIndex()
        self._watcher: FileWatcher | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def startup(self) -> None:
        await self._db.connect()
        await self._load_or_rebuild_index()
        self._titles.build(await self._db.get_all_files(), self._config.folder)

    async def shutdown(self) -> None:
        self._index.save()
        await self._db.close()

    async def _load_or_rebuild_index(self) -> None:
        if self._config.bm25_index_dir.exists() and any(self._config.bm25_index_dir.iterdir()):
            self._index.load_or_create()
        else:
            segments = await self._db.get_all_segments()
            if segments:
                doc_ids = self._index.rebuild_from_segments(segments)
                await self._db.update_bm25_doc_ids(segments, doc_ids)
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

        # Rebuild BM25 from scratch to eliminate ghost entries from incremental soft-deletes
        segments = await self._db.get_all_segments()
        doc_ids = self._index.rebuild_from_segments(segments)
        await self._db.update_bm25_doc_ids(segments, doc_ids)

    async def search(
        self,
        query: str,
        top_k: int | None = None,
        passages_per_document: int = 2,
    ) -> list[DocumentResult]:
        """Search the corpus and return ranked documents, best passages first.

        Results are documents, not segments: a single file that matches in
        twenty places is one result with its best passages attached, rather
        than twenty rows crowding out every other document.
        """
        k = top_k or self._config.top_k
        query = query.strip()
        if not query:
            return []

        # Over-fetch passages so grouping still has enough distinct documents
        # left after several passages collapse into the same file.
        hits = self._index.search(query, k * _CANDIDATE_FACTOR)
        title_scores = self._titles.search(query, k * _CANDIDATE_FACTOR)
        if not hits:
            return []

        resolved = await self._db.get_segments_by_bm25_ids([doc_id for doc_id, _ in hits])

        by_file: dict[int, DocumentResult] = {}
        for doc_id, score in hits:
            entry = resolved.get(doc_id)
            if entry is None:
                continue
            seg, file_id, mime_type = entry

            doc = by_file.get(file_id)
            if doc is None:
                doc = DocumentResult(
                    file_id=file_id,
                    file_path=seg.file_path,
                    mime_type=mime_type,
                    score=0.0,
                )
                by_file[file_id] = doc

            doc.passages.append(
                PassageResult(
                    segment_id=seg.id,
                    score=score,
                    location_type=seg.location_type,
                    location_label=seg.location_label,
                    location_index=seg.location_index,
                    snippet=make_snippet(seg.content, query),
                    content=seg.content,
                )
            )

        for file_id, doc in by_file.items():
            doc.passages.sort(key=lambda p: p.score, reverse=True)
            doc.score = _document_score(doc.passages)
            doc.score += _TITLE_WEIGHT * title_scores.get(file_id, 0.0)
            doc.passages = doc.passages[:passages_per_document]

        ranked = sorted(by_file.values(), key=lambda d: d.score, reverse=True)
        return ranked[:k]

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
