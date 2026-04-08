from __future__ import annotations

from pathlib import Path

import pytest

from docsearch.extraction.extractor import extract
from docsearch.metadata.models import ExtractedDoc, Segment
from docsearch.segmentation.segmenter import (
    _MAX_CHARS,
    _MIN_CHARS,
    _recursive_split,
    _segment_id,
    _split_if_too_long,
    segment,
)


def _make_doc(path: str, text: str, mime: str = "text/plain") -> ExtractedDoc:
    return ExtractedDoc(path=path, text=text, mime_type=mime, metadata={})


def _make_segment(seg_id: str, content: str, label: str = "Block 1", index: int = 0) -> Segment:
    return Segment(
        id=seg_id,
        file_path="/docs/file.txt",
        content=content,
        location_type="block",
        location_label=label,
        location_index=index,
        char_count=len(content),
    )


# ------------------------------------------------------------------
# Existing tests (structure-based segmentation)
# ------------------------------------------------------------------

def test_segment_markdown_by_headings(docs_dir: Path) -> None:
    doc = extract(docs_dir / "intro.md")
    segments = segment(doc)

    assert len(segments) >= 2
    assert all(isinstance(s, Segment) for s in segments)
    assert all(s.content.strip() for s in segments)


def test_segment_txt_blank_line_split() -> None:
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


# ------------------------------------------------------------------
# New tests: _recursive_split
# ------------------------------------------------------------------

def test_recursive_split_respects_max_chars() -> None:
    long_text = " ".join(["palabra"] * 500)  # ~3500 chars
    chunks = _recursive_split(long_text, _MAX_CHARS, ["\n\n", "\n", " "])
    assert all(len(c) <= _MAX_CHARS for c in chunks)


def test_recursive_split_short_text_unchanged() -> None:
    text = "Este texto es corto."
    chunks = _recursive_split(text, _MAX_CHARS, ["\n\n", "\n", " "])
    assert chunks == [text]


def test_recursive_split_preserves_content() -> None:
    paragraphs = ["Párrafo " + str(i) + " " + ("contenido " * 60) for i in range(5)]
    long_text = "\n\n".join(paragraphs)
    chunks = _recursive_split(long_text, _MAX_CHARS, ["\n\n", "\n", " "])
    joined = " ".join(chunks)
    # Every original word should appear somewhere in the joined output
    for para in paragraphs:
        first_word = para.split()[0]
        assert first_word in joined


def test_recursive_split_uses_coarsest_separator_first() -> None:
    # Text has both \n\n and \n — should prefer \n\n splits
    text = "Bloque uno con suficiente texto aqui.\n\nBloque dos con suficiente texto aqui."
    chunks = _recursive_split(text, 50, ["\n\n", "\n", " "])
    assert len(chunks) == 2
    assert "Bloque uno" in chunks[0]
    assert "Bloque dos" in chunks[1]


# ------------------------------------------------------------------
# New tests: _split_if_too_long
# ------------------------------------------------------------------

def test_split_if_too_long_returns_original_when_small() -> None:
    content = "Texto corto que no necesita ser dividido."
    seg = _make_segment("id1", content, label="Section A", index=0)
    result = _split_if_too_long(seg, _MAX_CHARS)

    assert len(result) == 1
    assert result[0].id == "id1"
    assert result[0].content == content


def test_split_if_too_long_label_suffix() -> None:
    content = ("Este es un párrafo largo. " * 60).strip()  # ~1500 chars
    seg = _make_segment("id1", content, label="# Introducción", index=0)
    result = _split_if_too_long(seg, _MAX_CHARS)

    assert len(result) > 1
    for s in result:
        assert " › " in s.location_label
        assert s.location_label.startswith("# Introducción")


def test_split_if_too_long_all_chunks_within_limit() -> None:
    content = ("palabra " * 300).strip()  # ~2400 chars
    seg = _make_segment("id1", content, label="Document", index=0)
    result = _split_if_too_long(seg, _MAX_CHARS)

    assert all(len(s.content) <= _MAX_CHARS for s in result)


def test_split_if_too_long_inherits_location_type() -> None:
    content = ("texto de sección " * 80).strip()
    seg = Segment(
        id="id1",
        file_path="/docs/file.md",
        content=content,
        location_type="section",
        location_label="# Mi Sección",
        location_index=2,
        char_count=len(content),
    )
    result = _split_if_too_long(seg, _MAX_CHARS)
    assert all(s.location_type == "section" for s in result)


def test_split_if_too_long_unique_ids() -> None:
    content = ("contenido largo para forzar la división en múltiples segmentos. " * 50).strip()
    seg = _make_segment("id1", content, label="Block 1", index=0)
    result = _split_if_too_long(seg, _MAX_CHARS)
    ids = [s.id for s in result]
    assert len(ids) == len(set(ids)), "Sub-segment IDs must be unique"


# ------------------------------------------------------------------
# New test: end-to-end size limit
# ------------------------------------------------------------------

def test_segment_applies_size_limit_end_to_end() -> None:
    # Single large paragraph with no headings — forces recursive split
    long_para = ("Esta es una oración larga con mucho contenido. " * 80).strip()
    doc = _make_doc("/docs/largo.txt", long_para)
    segments = segment(doc)

    assert segments, "Should produce at least one segment"
    assert all(s.char_count <= _MAX_CHARS for s in segments), (
        f"All segments must be <= {_MAX_CHARS} chars, got: {[s.char_count for s in segments]}"
    )


def test_segment_id_uniqueness_after_split() -> None:
    # Large doc with one section > 1024 chars
    long_section = "# Sección Larga\n\n" + ("contenido relevante para búsqueda. " * 50)
    doc = _make_doc("/docs/file.md", long_section, mime="text/markdown")
    segments = segment(doc)

    ids = [s.id for s in segments]
    assert len(ids) == len(set(ids)), "Sub-segment IDs must be unique after recursive split"
