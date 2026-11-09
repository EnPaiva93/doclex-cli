from __future__ import annotations

import shutil
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Self

from doclex.config import Config
from doclex.ingestion.scanner import ChangeSet
from doclex.metadata.models import DocumentResult, FileRecord
from doclex.pipeline import Pipeline


ProgressCallback = Callable[[Path, str], None]


class EngineError(Exception):
    pass


class IndexMissingError(EngineError):
    """The project has never been indexed, so there is nothing to read."""

    def __init__(self, folder: Path) -> None:
        super().__init__(f"No index found for {folder}")
        self.folder = folder


class FileOutsideProjectError(EngineError):
    def __init__(self, path: Path, folder: Path) -> None:
        super().__init__(f"{path} is not inside {folder}")
        self.path = path
        self.folder = folder


class _Session:
    """An opened project: lifecycle plus the inspection both roles need.

    Clients (CLI, MCP) talk to `Indexer` and `Searcher`, never to the pipeline,
    the index or the database directly. Both report through return values,
    exceptions and progress callbacks; neither prints.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        self._started: Pipeline | None = None

    @property
    def config(self) -> Config:
        return self._config

    def _prepare(self) -> None:
        """Hook run before the pipeline opens."""

    async def start(self) -> None:
        self._prepare()
        # Built here, not in __init__: its stores create their folders on construction.
        pipeline = Pipeline(self._config)
        await pipeline.startup()
        self._started = pipeline

    async def close(self) -> None:
        if self._started is not None:
            await self._started.shutdown()
            self._started = None

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    @property
    def _pipeline(self) -> Pipeline:
        if self._started is None:
            raise RuntimeError(
                f"{type(self).__name__} not started. Call start() or use 'async with'."
            )
        return self._started

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    async def status(self) -> dict:
        """Corpus summary, including files changed on disk since the last index."""
        return await self._pipeline.corpus_status()

    async def file_status(self, path: Path) -> dict:
        return await self._pipeline.get_file_status(path.resolve())

    async def files(self, status: str | None = None) -> list[FileRecord]:
        return await self._pipeline.list_files(status)

    async def files_without_text(self) -> list[FileRecord]:
        return await self._pipeline.files_without_text()


class Indexer(_Session):
    """The write side: brings a project's index in line with its folder.

    Only one indexer should run per project at a time; it is the single writer
    of the index and the database.

        async with Indexer(Config(folder)) as indexer:
            await indexer.apply(await indexer.scan())

    Nothing is written until `start`, so a request rejected before then (a file
    outside the project, say) leaves no empty cache behind.
    """

    def _prepare(self) -> None:
        self._config.ensure_dirs()

    async def scan(self) -> ChangeSet:
        """Compare the folder against the index: what is new, modified, deleted."""
        return await self._pipeline.reconcile()

    async def apply(
        self,
        changes: ChangeSet,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        await self._pipeline.apply_changes(changes, on_progress=on_progress)

    async def reindex_files(
        self,
        paths: Iterable[Path],
        on_progress: ProgressCallback | None = None,
    ) -> None:
        """Re-extract specific files. All are checked before any is touched."""
        for path in self.resolve_files(paths):
            if on_progress:
                on_progress(path, "reindexing")
            await self._pipeline.reindex_file(path)

    async def reindex_all(self, on_progress: ProgressCallback | None = None) -> None:
        await self._pipeline.reindex_all(on_progress=on_progress)

    def resolve_files(self, paths: Iterable[Path]) -> list[Path]:
        """Absolute paths for files inside the project, or an error for the first that is not.

        The index stores absolute paths; a relative one would be taken for a new
        file. Needs no `start`, so callers can validate before anything is written.
        """
        resolved: list[Path] = []
        for path in paths:
            absolute = path.resolve()
            if not absolute.exists():
                raise FileNotFoundError(f"File not found: {path}")
            if not absolute.is_relative_to(self._config.folder):
                raise FileOutsideProjectError(path, self._config.folder)
            resolved.append(absolute)
        return resolved


class Searcher(_Session):
    """The read side: queries an index that an `Indexer` built.

        async with Searcher(Config(folder)) as searcher:
            results = await searcher.search("viaticos")

    It offers no way to change the corpus. Opening a project that was never
    indexed raises `IndexMissingError` rather than creating an empty one.
    """

    def __init__(self, config: Config) -> None:
        if not config.cache_dir.exists():
            raise IndexMissingError(config.folder)
        super().__init__(config)

    async def search(
        self,
        query: str,
        top_k: int | None = None,
        passages_per_document: int = 2,
    ) -> list[DocumentResult]:
        return await self._pipeline.search(
            query, top_k, passages_per_document=passages_per_document
        )

    async def index_is_outdated(self) -> bool:
        """Whether the index predates the current segmentation and needs --force."""
        return await self._pipeline.index_is_outdated()


def purge(config: Config) -> list[Path]:
    """Delete everything Doclex stored for a project. Returns what existed.

    The database is removed on its own when DOCLEX_DB_PATH placed it outside
    the cache directory; otherwise deleting the cache already takes it. Its
    WAL files go with it, or SQLite would replay them into a fresh database.
    """
    removed: list[Path] = []
    if config.cache_dir.exists():
        shutil.rmtree(config.cache_dir, ignore_errors=True)
        removed.append(config.cache_dir)
    for suffix in ("", "-wal", "-shm"):
        path = config.db_path.with_name(config.db_path.name + suffix)
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed
