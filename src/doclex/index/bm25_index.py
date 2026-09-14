from __future__ import annotations

import re
from pathlib import Path

from bm25x import BM25

from doclex.metadata.models import Highlight, Segment, Snippet


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

    def rebuild_from_segments(self, segments: list[Segment]) -> list[int]:
        """Rebuild the full index from a list of segments. Returns new bm25_doc_ids."""
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index = BM25()
        doc_ids: list[int] = []
        if segments:
            doc_ids = self._index.add([s.content for s in segments])
        self.save()
        return doc_ids

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


def query_terms(query: str) -> list[str]:
    """Split a query the way BM25X tokenizes documents.

    Splitting on non-alphanumerics (not just whitespace) keeps acronyms and
    punctuation-joined terms usable as anchors, e.g. "GT/DPM" -> ["gt", "dpm"].
    """
    return [t for t in re.split(r"\W+", query.lower()) if t]


def make_snippet(content: str, query: str, window: int = _SNIPPET_WINDOW) -> Snippet:
    """Extract the window with the highest density of query-term matches.

    Returns the excerpt plus the offsets of every query match inside it.
    Highlights are offsets rather than markup so each frontend renders them
    its own way; see Snippet.

    Among all match positions, the one whose surrounding window covers the most
    distinct query terms wins (ties broken by total match count, then earliest
    position) — not just the first occurrence of the first term — so the snippet
    favors the part of the segment where the query actually clusters. The window
    is then snapped to word boundaries so it never cuts a word in half.
    """
    terms = query_terms(query)

    matches: list[tuple[int, int, str]] = [
        (m.start(), m.end(), term)
        for term in terms
        for m in re.finditer(re.escape(term), content, re.IGNORECASE)
    ]

    if not matches:
        text = content[:window].rstrip()
        if len(content) > window:
            text += "\u2026"
        return Snippet(text=text, highlights=[])

    def density(match: tuple[int, int, str]) -> tuple[int, int, int]:
        pos = match[0]
        lo, hi = pos - window // 2, pos + window // 2
        nearby = [t for s, _, t in matches if lo <= s <= hi]
        return (len(set(nearby)), len(nearby), -pos)

    match_start, match_end, _ = max(matches, key=density)

    start = max(0, match_start - window // 2)
    end = min(len(content), match_end + window // 2)
    snippet = content[start:end]

    # Snap to word boundaries, tracking how far `start` moved so the highlight
    # offsets below stay aligned with the final text.
    if start > 0:
        ws_positions = [p for p in (snippet.find(" "), snippet.find("\n"), snippet.find("\t")) if p != -1]
        if ws_positions:
            trimmed = min(ws_positions) + 1
            snippet = snippet[trimmed:]
            start += trimmed
    if end < len(content):
        last_ws = max(snippet.rfind(" "), snippet.rfind("\n"), snippet.rfind("\t"))
        if last_ws > 0:
            end -= len(snippet) - last_ws
            snippet = snippet[:last_ws]

    stripped = snippet.strip()
    if stripped:
        start += len(snippet) - len(snippet.lstrip())
        snippet = stripped
    else:
        snippet = content[start:end].strip()

    prefix = "\u2026" if start > 0 else ""
    suffix = "\u2026" if end < len(content) else ""

    # Offsets are relative to the excerpt, shifted by any leading ellipsis.
    highlights = [
        Highlight(start=s - start + len(prefix), end=e - start + len(prefix))
        for s, e, _ in matches
        if s >= start and e <= end
    ]
    highlights.sort(key=lambda h: h.start)

    return Snippet(text=prefix + snippet + suffix, highlights=highlights)
