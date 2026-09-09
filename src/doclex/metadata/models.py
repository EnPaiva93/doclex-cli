from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FileRecord:
    path: str
    hash: str
    mtime: float
    size: int
    mime_type: str
    status: str  # pending | indexed | error
    id: int | None = None
    indexed_at: float | None = None
    error_msg: str | None = None


@dataclass
class ExtractedDoc:
    path: str
    text: str
    mime_type: str
    metadata: dict = field(default_factory=dict)
    tables: list = field(default_factory=list)      # kreuzberg extracted tables


@dataclass
class Segment:
    id: str           # sha256(path + location_label + str(location_index))
    file_path: str
    content: str
    location_type: str   # page | sheet | section | block | table
    location_label: str  # "Page 3", "Sheet: Ventas", "# Introducción"
    location_index: int
    char_count: int = 0
    bm25_doc_id: int | None = None  # internal BM25X index assigned on add()
    section_id: str | None = None   # reference to tree node id
    level: int = 0                  # heading level (1-3); 0 for non-heading nodes

    def __post_init__(self) -> None:
        if not self.char_count:
            self.char_count = len(self.content)


@dataclass
class SearchResult:
    segment_id: str
    score: float
    file_path: str
    mime_type: str
    location_type: str
    location_label: str
    content: str
    snippet: str  # ~200 chars alrededor del match


@dataclass
class Highlight:
    """Offsets of a query-term match inside a Snippet's text."""
    start: int
    end: int


@dataclass
class Snippet:
    """A short excerpt of a segment, with the query matches located in it.

    Highlights are offsets into `text`, not markup, so each frontend decides
    how to render them (bold in the CLI, <mark> on the web, raw in JSON).
    """
    text: str
    highlights: list[Highlight] = field(default_factory=list)

    def __str__(self) -> str:
        return self.text


@dataclass
class PassageResult:
    """One matching location inside a document."""
    segment_id: str
    score: float
    location_type: str
    location_label: str
    location_index: int
    snippet: Snippet
    content: str


@dataclass
class DocumentResult:
    """A search result as the user sees it: one document, its best passages."""
    file_id: int
    file_path: str
    mime_type: str
    score: float
    passages: list[PassageResult] = field(default_factory=list)

    @property
    def filename(self) -> str:
        from pathlib import PurePath
        return PurePath(self.file_path).name
