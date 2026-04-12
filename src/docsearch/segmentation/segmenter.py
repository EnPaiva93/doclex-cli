from __future__ import annotations

import hashlib
import re
from pathlib import Path

from kreuzberg import ExtractionConfig, extract_file_sync
from kreuzberg.exceptions import KreuzbergError

from docsearch.metadata.models import ExtractedDoc, Segment

# Minimum chars for a segment to be worth indexing
_MIN_CHARS = 30

# Maximum chars per segment — recursive splitter enforces this
_MAX_CHARS = 1024

# Headings: Markdown / plain text
_HEADING_RE = re.compile(
    r"(?:^|\n)(#{1,3}\s+.+|(?=\S).+\n[=\-]{3,})", re.MULTILINE
)

# Separators tried in order by the recursive splitter
_SEPARATORS = ["\n\n", "\n", " "]


def segment(doc: ExtractedDoc) -> list[Segment]:
    """Segment an ExtractedDoc into indexable units based on file type.

    Strategy:
    1. Structure-based segmentation (headings, pages, sheets, tables)
    2. Any segment > _MAX_CHARS is recursively split preserving semantic boundaries
    """
    suffix = Path(doc.path).suffix.lower()

    if suffix == ".pdf":
        raw = _segment_pdf(doc)
    elif suffix in (".xlsx",):
        raw = _segment_spreadsheet(doc)
    elif suffix == ".csv":
        raw = _segment_csv(doc)
    elif suffix in (".docx", ".md", ".txt"):
        raw = _segment_text(doc)
    else:
        raw = _segment_fallback(doc)

    return _apply_size_limit(raw, _MAX_CHARS)


# ------------------------------------------------------------------
# PDF — page-by-page via form-feed split, fallback to full text
# ------------------------------------------------------------------

def _segment_pdf(doc: ExtractedDoc) -> list[Segment]:
    """Segment PDF: markdown-based when precise mode produced headings, otherwise page-based."""
    segments: list[Segment] = []

    if _has_markdown_headings(doc.text):
        # precise mode: Kreuzberg returned markdown with heading structure
        segments = _segment_text(doc)
    else:
        pages = doc.text.split("\f")
        segments = _make_segments(doc, pages, "page", "Page") if len(pages) > 1 else _segment_fallback(doc)

    # Append table segments from precise mode (result.tables)
    if doc.tables:
        offset = len(segments)
        for i, table in enumerate(doc.tables):
            content = _table_to_text(table)
            if len(content) >= _MIN_CHARS:
                label = getattr(table, "name", None) or f"Table {i + 1}"
                segments.append(_make_segment(doc, content, "table", label, offset + i))

    return segments or _segment_fallback(doc)


def _has_markdown_headings(text: str) -> bool:
    return bool(re.search(r"(?:^|\n)#{1,3} ", text))


# ------------------------------------------------------------------
# XLSX — sheet-by-sheet via Kreuzberg tables
# ------------------------------------------------------------------

def _segment_spreadsheet(doc: ExtractedDoc) -> list[Segment]:
    try:
        config = ExtractionConfig()
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

    return _segment_fallback(doc)


# ------------------------------------------------------------------
# CSV — table or chunked rows
# ------------------------------------------------------------------

def _segment_csv(doc: ExtractedDoc) -> list[Segment]:
    try:
        config = ExtractionConfig()
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

    # Split on Markdown headings (# / ## / ###)
    parts = re.split(r"\n(?=#{1,3} )", text)

    if len(parts) <= 1:
        # No headings — split on blank lines, no tree structure
        parts = re.split(r"\n{2,}", text)
        segments: list[Segment] = []
        for i, part in enumerate(parts):
            part = part.strip()
            if len(part) < _MIN_CHARS:
                continue
            first_line = part.splitlines()[0].lstrip("#").strip()
            label = first_line[:80] if first_line else f"Block {i + 1}"
            segments.append(_make_segment(doc, part, "block", label, i))
        return segments or _segment_fallback(doc)

    # Parse heading parts
    parsed: list[tuple[int, str, str, str, int]] = []  # (level, title, node_id, content, index)
    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue
        first_line = part.splitlines()[0]
        m = re.match(r"^(#{1,3}) ", first_line)
        level = len(m.group(1)) if m else 0
        title = first_line.lstrip("#").strip()[:80] or f"Block {i + 1}"
        node_id = _segment_id(doc.path, title, i)
        parsed.append((level, title, node_id, part, i))

    # Create segments with level and section_id
    segments = []
    for level, title, node_id, content, i in parsed:
        if len(content) < _MIN_CHARS:
            continue
        location_type = "section" if level <= 2 else "block"
        segments.append(Segment(
            id=node_id,
            file_path=doc.path,
            content=content,
            location_type=location_type,
            location_label=title,
            location_index=i,
            char_count=len(content),
            section_id=node_id,
            level=level,
        ))

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
# Size enforcement — recursive character splitter
# ------------------------------------------------------------------

def _apply_size_limit(segments: list[Segment], max_chars: int) -> list[Segment]:
    """Post-process segments: split any that exceed max_chars."""
    result: list[Segment] = []
    for seg in segments:
        result.extend(_split_if_too_long(seg, max_chars))
    return result


def _split_if_too_long(seg: Segment, max_chars: int) -> list[Segment]:
    """Return the segment as-is if within limit, or split it recursively."""
    if len(seg.content) <= max_chars:
        return [seg]

    chunks = _recursive_split(seg.content, max_chars, _SEPARATORS)

    result: list[Segment] = []
    for i, chunk in enumerate(chunks):
        chunk = chunk.strip()
        if len(chunk) < _MIN_CHARS:
            continue
        sub_label = f"{seg.location_label} › {i + 1}"
        sub_index = seg.location_index * 1000 + i
        result.append(Segment(
            id=_segment_id(seg.file_path, sub_label, sub_index),
            file_path=seg.file_path,
            content=chunk,
            location_type=seg.location_type,
            location_label=sub_label,
            location_index=sub_index,
            char_count=len(chunk),
            section_id=seg.section_id,
            level=seg.level,
        ))

    # Guard: never drop a valid segment entirely
    return result if result else [seg]


def _recursive_split(text: str, max_chars: int, separators: list[str]) -> list[str]:
    """Split text into chunks of at most max_chars using the coarsest separator first.

    Strategy:
    1. Try to split on the coarsest separator.
    2. Greedily merge consecutive pieces back together up to max_chars.
    3. Pieces that are still too large are recursively split with the next separator.
    """
    if len(text) <= max_chars:
        return [text]

    if not separators:
        # Hard character slice as last resort
        return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]

    sep, *remaining = separators
    raw_parts = text.split(sep)

    if len(raw_parts) == 1:
        # Separator not present in this text — try the next one
        return _recursive_split(text, max_chars, remaining)

    # First pass: recursively handle pieces that are individually too large
    good_parts: list[str] = []
    for part in raw_parts:
        part = part.strip()
        if not part:
            continue
        if len(part) <= max_chars:
            good_parts.append(part)
        else:
            good_parts.extend(_recursive_split(part, max_chars, remaining))

    # Second pass: greedy merge — combine consecutive parts up to max_chars
    chunks: list[str] = []
    current = ""
    for part in good_parts:
        candidate = (current + sep + part).strip() if current else part
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = part
    if current:
        chunks.append(current)

    return chunks


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


def _table_to_text(table: object) -> str:
    """Convert a Kreuzberg ExtractedTable to plain text."""
    if hasattr(table, "content") and table.content:
        return str(table.content)
    if hasattr(table, "rows") and table.rows:
        return "\n".join("\t".join(str(c) for c in row) for row in table.rows)
    return str(table)


def _segment_id(path: str, label: str, index: int) -> str:
    raw = f"{path}|{label}|{index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
