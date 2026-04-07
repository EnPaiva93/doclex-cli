from __future__ import annotations

from pathlib import Path

import pytest

from docsearch.extraction.extractor import extract
from docsearch.metadata.models import ExtractedDoc, Segment
from docsearch.segmentation.segmenter import segment, _segment_id


def _make_doc(path: str, text: str, mime: str = "text/plain") -> ExtractedDoc:
    return ExtractedDoc(path=path, text=text, mime_type=mime, metadata={})


def test_segment_markdown_by_headings(docs_dir: Path) -> None:
    doc = extract(docs_dir / "intro.md")
    segments = segment(doc)

    assert len(segments) >= 2
    assert all(isinstance(s, Segment) for s in segments)
    # Each segment has content
    assert all(s.content.strip() for s in segments)


def test_segment_txt_fallback_to_blocks() -> None:
    doc = _make_doc("/docs/file.txt", "Line one.\nLine two.\n\nAnother paragraph here with enough text to index.")
    segments = segment(doc)

    assert len(segments) >= 1
    assert all(s.location_type in ("section", "block") for s in segments)


def test_segment_markdown_location_types() -> None:
    text = "# Title\n\nSome intro content here.\n\n## Section A\n\nContent of section A with enough text."
    doc = _make_doc("/docs/file.md", text, mime="text/markdown")
    segments = segment(doc)

    types = {s.location_type for s in segments}
    assert types <= {"section", "block"}


def test_segment_csv(docs_dir: Path) -> None:
    doc = extract(docs_dir / "datos.csv")
    segments = segment(doc)

    assert len(segments) >= 1
    assert all(s.location_type in ("table", "block") for s in segments)


def test_segment_ids_are_stable() -> None:
    doc = _make_doc("/docs/file.md", "# Hello\n\nSome content here that is long enough to be indexed.")
    s1 = segment(doc)
    s2 = segment(doc)

    assert [s.id for s in s1] == [s.id for s in s2]


def test_segment_id_uniqueness() -> None:
    doc = _make_doc(
        "/docs/file.md",
        "# Section A\n\nContent A with enough text.\n\n## Section B\n\nContent B with enough text.",
        mime="text/markdown",
    )
    segments = segment(doc)
    ids = [s.id for s in segments]
    assert len(ids) == len(set(ids)), "Segment IDs must be unique"


def test_segment_minimum_length_filter() -> None:
    doc = _make_doc("/docs/tiny.txt", "ok")
    segments = segment(doc)
    assert segments == [], "Segments below min length should be filtered out"


def test_segment_char_count_matches_content() -> None:
    text = "# Heading\n\nThis is a sufficiently long paragraph to be indexed by the system."
    doc = _make_doc("/docs/file.md", text)
    segments = segment(doc)
    assert segments
    for s in segments:
        assert s.char_count == len(s.content)
