from __future__ import annotations

from pathlib import Path

from bm25x import BM25

from docsearch.metadata.models import Segment


_SNIPPET_WINDOW = 200  # chars around the query match for snippet generation


class BM25Index:
    """Wrapper around BM25X with persistence and segment-level CRUD."""

    def __init__(self, index_dir: Path) -> None:
        self._dir = index_dir
        self._index: BM25 | None = None

    def load_or_create(self) -> None:
        """Load existing index from disk or create an empty one."""
        if self._dir.exists() and any(self._dir.iterdir()):
            self._index = BM25.load(str(self._dir))
        else:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._index = BM25()

    def rebuild_from_segments(self, segments: list[Segment]) -> None:
        """Rebuild the full index from a list of segments (used at startup)."""
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index = BM25()
        if segments:
            self._index.add([s.content for s in segments])
        self.save()

    @property
    def _bm25(self) -> BM25:
        if self._index is None:
            raise RuntimeError("Index not loaded. Call load_or_create() first.")
        return self._index

    def add(self, segments: list[Segment]) -> list[int]:
        """Add segments to the index. Returns assigned bm25_doc_ids."""
        if not segments:
            return []
        doc_ids: list[int] = self._bm25.add([s.content for s in segments])
        return doc_ids

    def delete(self, bm25_doc_ids: list[int]) -> None:
        """Remove segments by their BM25X doc ids."""
        if bm25_doc_ids:
            self._bm25.delete(bm25_doc_ids)

    def search(self, query: str, k: int) -> list[tuple[int, float]]:
        """Search the index. Returns list of (bm25_doc_id, score)."""
        if len(self._bm25) == 0:
            return []
        results = self._bm25.search(query, k)
        return [(doc_id, float(score)) for doc_id, score in results]

    def save(self) -> None:
        self._bm25.save(str(self._dir))

    def __len__(self) -> int:
        return len(self._bm25) if self._index is not None else 0


def make_snippet(content: str, query: str, window: int = _SNIPPET_WINDOW) -> str:
    """Extract a snippet of text around the first occurrence of any query term."""
    lower = content.lower()
    terms = query.lower().split()
    pos = -1
    for term in terms:
        idx = lower.find(term)
        if idx != -1:
            pos = idx
            break

    if pos == -1:
        return content[:window].rstrip() + ("…" if len(content) > window else "")

    start = max(0, pos - window // 2)
    end = min(len(content), pos + window // 2)
    snippet = content[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(content):
        snippet = snippet + "…"
    return snippet
