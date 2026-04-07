from __future__ import annotations

import hashlib
import re
from pathlib import Path

from kreuzberg import ExtractionConfig, extract_file_sync
from kreuzberg.exceptions import KreuzbergError

from docsearch.metadata.models import ExtractedDoc, Segment

# Minimum chars for a segment to be worth indexing
_MIN_CHARS = 30

# Headings: Markdown / plain text
_HEADING_RE = re.compile(
    r"(?:^|\n)(#{1,3}\s+.+|(?=\S).+\n[=\-]{3,})", re.MULTILINE
)


def segment(doc: ExtractedDoc) -> list[Segment]:
    """Segment an ExtractedDoc into indexable units based on file type."""
    suffix = Path(doc.path).suffix.lower()

    if suffix == ".pdf":
        return _segment_pdf(doc)
    elif suffix in (".xlsx",):
        return _segment_spreadsheet(doc)
    elif suffix == ".csv":
        return _segment_csv(doc)
    elif suffix in (".docx", ".md", ".txt"):
        return _segment_text(doc)
    else:
        return _segment_fallback(doc)


# ------------------------------------------------------------------
# PDF — page-by-page via Kreuzberg metadata or form-feed split
# ------------------------------------------------------------------

def _segment_pdf(doc: ExtractedDoc) -> list[Segment]:
    """Try to extract PDF page-by-page; fall back to text blocks."""
    try:
        config = ExtractionConfig(disable_ocr=True, result_format="element_based")
        result = extract_file_sync(doc.path, None, config)
        # element_based returns content with page markers in metadata
        page_count = result.metadata.get("page_count") or result.metadata.get("pages")
    except KreuzbergError:
        page_count = None

    # Try form-feed split (\f separates pages in many PDF extractors)
    pages = doc.text.split("\f")
    if len(pages) > 1:
        return _make_segments(doc, pages, "page", "Page")

    # Fall back to blocks of ~1500 chars
    return _segment_by_blocks(doc, block_size=1500, location_type="block", label_prefix="Block")


# ------------------------------------------------------------------
# XLSX — sheet-by-sheet via Kreuzberg tables
# ------------------------------------------------------------------

def _segment_spreadsheet(doc: ExtractedDoc) -> list[Segment]:
    try:
        config = ExtractionConfig(disable_ocr=True)
        result = extract_file_sync(doc.path, None, config)
        if result.tables:
            segments: list[Segment] = []
            for i, table in enumerate(result.tables):
                label = getattr(table, "name", None) or f"Sheet {i + 1}"
                content = _table_to_text(table)
                if len(content) >= _MIN_CHARS:
                    segments.append(_make_segment(doc, content, "sheet", label, i))
            if segments:
                return segments
    except KreuzbergError:
        pass

    # Fallback: treat full text as a single table segment
    return _segment_fallback(doc)


# ------------------------------------------------------------------
# CSV — table or chunked rows
# ------------------------------------------------------------------

def _segment_csv(doc: ExtractedDoc) -> list[Segment]:
    try:
        config = ExtractionConfig(disable_ocr=True)
        result = extract_file_sync(doc.path, None, config)
        if result.tables:
            content = _table_to_text(result.tables[0])
            return [_make_segment(doc, content, "table", "Table", 0)]
    except KreuzbergError:
        pass

    lines = [l for l in doc.text.splitlines() if l.strip()]
    if not lines:
        return []

    chunk_size = 50
    segments: list[Segment] = []
    for i in range(0, len(lines), chunk_size):
        chunk = "\n".join(lines[i : i + chunk_size])
        label = f"Rows {i + 1}–{min(i + chunk_size, len(lines))}"
        segments.append(_make_segment(doc, chunk, "table", label, i // chunk_size))
    return segments


# ------------------------------------------------------------------
# DOCX / MD / TXT — heading-based segmentation
# ------------------------------------------------------------------

def _segment_text(doc: ExtractedDoc) -> list[Segment]:
    text = doc.text.strip()
    if not text:
        return []

    # Split on Markdown headings (# / ## / ###) or underline headings
    parts = re.split(r"\n(?=#{1,3} )", text)

    if len(parts) <= 1:
        # No headings — split on blank lines
        parts = re.split(r"\n{2,}", text)

    segments: list[Segment] = []
    for i, part in enumerate(parts):
        part = part.strip()
        if len(part) < _MIN_CHARS:
            continue
        first_line = part.splitlines()[0].lstrip("#").strip()
        label = first_line[:80] if first_line else f"Block {i + 1}"
        location_type = "section" if part.startswith("#") else "block"
        segments.append(_make_segment(doc, part, location_type, label, i))

    return segments or _segment_fallback(doc)


# ------------------------------------------------------------------
# Fallback — whole text as single block
# ------------------------------------------------------------------

def _segment_fallback(doc: ExtractedDoc) -> list[Segment]:
    text = doc.text.strip()
    if len(text) < _MIN_CHARS:
        return []
    return [_make_segment(doc, text, "block", "Document", 0)]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _make_segments(
    doc: ExtractedDoc,
    parts: list[str],
    location_type: str,
    label_prefix: str,
) -> list[Segment]:
    segments: list[Segment] = []
    for i, part in enumerate(parts):
        part = part.strip()
        if len(part) < _MIN_CHARS:
            continue
        label = f"{label_prefix} {i + 1}"
        segments.append(_make_segment(doc, part, location_type, label, i))
    return segments


def _make_segment(
    doc: ExtractedDoc,
    content: str,
    location_type: str,
    location_label: str,
    location_index: int,
) -> Segment:
    seg_id = _segment_id(doc.path, location_label, location_index)
    return Segment(
        id=seg_id,
        file_path=doc.path,
        content=content,
        location_type=location_type,
        location_label=location_label,
        location_index=location_index,
        char_count=len(content),
    )


def _segment_by_blocks(
    doc: ExtractedDoc,
    block_size: int,
    location_type: str,
    label_prefix: str,
) -> list[Segment]:
    text = doc.text.strip()
    segments: list[Segment] = []
    for i in range(0, len(text), block_size):
        chunk = text[i : i + block_size].strip()
        if len(chunk) < _MIN_CHARS:
            continue
        label = f"{label_prefix} {i // block_size + 1}"
        segments.append(_make_segment(doc, chunk, location_type, label, i // block_size))
    return segments


def _table_to_text(table: object) -> str:
    """Convert a Kreuzberg ExtractedTable to plain text."""
    # ExtractedTable has .rows (list of lists) or .content
    if hasattr(table, "content") and table.content:
        return str(table.content)
    if hasattr(table, "rows") and table.rows:
        return "\n".join("\t".join(str(c) for c in row) for row in table.rows)
    return str(table)


def _segment_id(path: str, label: str, index: int) -> str:
    raw = f"{path}|{label}|{index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
