"""Doclex: local document search with structural segmentation and BM25.

This module is the public API. Clients (the CLI, an MCP server) import from
here and nothing deeper; the rest of the package is internal and may change
between minor versions.

    from doclex import Config, Indexer, Searcher

    async with Indexer(Config(folder)) as indexer:
        await indexer.apply(await indexer.scan())

    async with Searcher(Config(folder)) as searcher:
        results = await searcher.search("viaticos")
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from doclex.config import SUPPORTED_EXTENSIONS, Config
from doclex.engine import (
    EngineError,
    FileOutsideProjectError,
    Indexer,
    IndexMissingError,
    ProgressCallback,
    Searcher,
    purge,
)
from doclex.ingestion.scanner import ChangeSet
from doclex.metadata.models import (
    DocumentResult,
    FileRecord,
    Highlight,
    PassageResult,
    Segment,
    Snippet,
)
from doclex.registry import (
    Project,
    ProjectAlreadyExistsError,
    ProjectFolderNotFoundError,
    ProjectNotFoundError,
    ProjectOverlapError,
    ProjectRegistry,
    RegistryError,
)
from doclex.results import clean_label, results_to_dict

try:
    __version__ = version("doclex-cli")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0"

__all__ = [
    # Configuration
    "Config",
    "SUPPORTED_EXTENSIONS",
    # Indexing and searching
    "Indexer",
    "Searcher",
    "purge",
    "ChangeSet",
    "ProgressCallback",
    # Results
    "DocumentResult",
    "PassageResult",
    "Segment",
    "Snippet",
    "Highlight",
    "FileRecord",
    "clean_label",
    "results_to_dict",
    # Projects
    "Project",
    "ProjectRegistry",
    # Errors
    "EngineError",
    "IndexMissingError",
    "FileOutsideProjectError",
    "RegistryError",
    "ProjectNotFoundError",
    "ProjectAlreadyExistsError",
    "ProjectFolderNotFoundError",
    "ProjectOverlapError",
    "__version__",
]
