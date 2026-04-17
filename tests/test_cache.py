from __future__ import annotations

from pathlib import Path

import pytest

from docsearch.cache.store import CacheStore, _build_index, _flatten_index
from docsearch.metadata.models import ExtractedDoc, Segment


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _doc(path: str = "/docs/file.txt", mime: str = "text/plain") -> ExtractedDoc:
    return ExtractedDoc(path=path, text="texto de prueba", mime_type=mime, metadata={"author": "test"})


def _seg(
    seg_id: str,
    content: str = "Contenido de prueba suficientemente largo.",
    label: str = "Block 1",
    index: int = 0,
    level: int = 0,
    file_path: str = "/docs/file.txt",
) -> Segment:
    return Segment(
        id=seg_id,
        file_path=file_path,
        content=content,
        location_type="section" if level > 0 else "block",
        location_label=label,
        location_index=index,
        char_count=len(content),
        level=level,
    )


# ------------------------------------------------------------------
# CacheStore — put / get / delete
# ------------------------------------------------------------------

def test_get_on_empty_cache_returns_none(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    assert store.get("/docs/nonexistent.txt") is None


def test_put_and_get_round_trip(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    doc = _doc()
    segs = [
        _seg("seg1", "Primer bloque con contenido suficiente.", index=0),
        _seg("seg2", "Segundo bloque con más texto aquí.", index=1),
    ]
    store.put(doc, segs)

    result = store.get("/docs/file.txt")
    assert result is not None
    recovered_doc, recovered_segs = result
    assert recovered_doc.path == "/docs/file.txt"
    assert recovered_doc.mime_type == "text/plain"
    assert len(recovered_segs) == 2


def test_put_overwrites_existing_entry(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    doc = _doc()

    store.put(doc, [_seg("old_seg", "contenido original")])
    store.put(doc, [_seg("new_seg", "contenido actualizado")])

    _, segs = store.get("/docs/file.txt")
    ids = {s.id for s in segs}
    assert "new_seg" in ids
    assert "old_seg" not in ids


def test_delete_removes_entry(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    store.put(_doc(), [_seg("seg1", "contenido válido para cache")])
    store.delete("/docs/file.txt")

    assert store.get("/docs/file.txt") is None


def test_delete_nonexistent_is_noop(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    store.delete("/docs/nonexistent.txt")  # must not raise


def test_put_creates_cache_dir_if_needed(tmp_path: Path) -> None:
    subdir = tmp_path / "deep" / "nested" / "cache"
    store = CacheStore(subdir)
    store.put(_doc(), [_seg("seg1", "contenido de prueba en dir profundo")])
    assert store.get("/docs/file.txt") is not None


def test_metadata_preserved_in_cache(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    doc = ExtractedDoc(
        path="/docs/doc.md",
        text="",
        mime_type="text/markdown",
        metadata={"source": "test", "page_count": 3},
    )
    store.put(doc, [_seg("seg1", "contenido con metadata relevante")])

    recovered_doc, _ = store.get("/docs/doc.md")
    assert recovered_doc.metadata["source"] == "test"
    assert recovered_doc.metadata["page_count"] == 3


def test_different_paths_use_different_cache_files(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    store.put(_doc("/docs/a.txt"), [_seg("seg_a", "Contenido del archivo A.")])
    store.put(_doc("/docs/b.txt"), [_seg("seg_b", "Contenido del archivo B.")])

    _, segs_a = store.get("/docs/a.txt")
    _, segs_b = store.get("/docs/b.txt")

    ids_a = {s.id for s in segs_a}
    ids_b = {s.id for s in segs_b}
    assert ids_a != ids_b


def test_content_preserved_in_round_trip(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    original_content = "Este es el contenido único del segmento para verificar round-trip."
    store.put(_doc(), [_seg("uniq1", original_content)])

    _, recovered = store.get("/docs/file.txt")
    all_content = " ".join(s.content for s in recovered)
    assert "contenido único" in all_content


# ------------------------------------------------------------------
# _build_index
# ------------------------------------------------------------------

def test_build_index_flat_creates_root_nodes(tmp_path: Path) -> None:
    segs = [
        _seg("s1", "Bloque uno con texto suficiente.", label="Block 1", index=0),
        _seg("s2", "Bloque dos con texto suficiente.", label="Block 2", index=1),
    ]
    idx = _build_index("documento", segs)

    assert idx["title"] == "documento"
    assert len(idx["nodes"]) == 2


def test_build_index_heading_segments_are_hierarchical(tmp_path: Path) -> None:
    segs = [
        _seg("h1", "# Sección A\n\nContenido A.", label="# Sección A", index=0, level=1),
        _seg("h2", "# Sección B\n\nContenido B.", label="# Sección B", index=1, level=1),
    ]
    idx = _build_index("documento", segs)

    assert len(idx["nodes"]) == 2


def test_build_index_assigns_prev_next_ids(tmp_path: Path) -> None:
    # Navigation links are only assigned in the hierarchical path (level > 0)
    segs = [
        _seg("s1", "# Sección A\n\nTexto A.", label="# Sección A", index=0, level=1),
        _seg("s2", "# Sección B\n\nTexto B.", label="# Sección B", index=1, level=1),
        _seg("s3", "# Sección C\n\nTexto C.", label="# Sección C", index=2, level=1),
    ]
    idx = _build_index("doc", segs)
    nodes = idx["nodes"]

    # First: no prev, has next
    assert nodes[0].get("prev_id") is None
    assert nodes[0].get("next_id") == nodes[1]["id"]

    # Middle: has both
    assert nodes[1].get("prev_id") == nodes[0]["id"]
    assert nodes[1].get("next_id") == nodes[2]["id"]

    # Last: has prev, no next
    assert nodes[2].get("prev_id") == nodes[1]["id"]
    assert nodes[2].get("next_id") is None


def test_build_index_leaf_nodes_have_no_title(tmp_path: Path) -> None:
    # _clean_nodes only runs in the hierarchical path (level > 0).
    # A single heading with no child nodes is a hierarchical leaf.
    segs = [_seg("s1", "# Heading\n\nContenido.", label="# Heading", index=0, level=1)]
    idx = _build_index("doc", segs)

    node = idx["nodes"][0]
    # _clean_nodes pops title from leaf nodes (nodes with no children)
    assert "title" not in node


def test_build_index_assigns_parent_id(tmp_path: Path) -> None:
    segs = [
        _seg("s1", "Bloque uno con texto.", label="Block 1", index=0),
        _seg("s2", "Bloque dos con texto.", label="Block 2", index=1),
    ]
    idx = _build_index("doc", segs)
    nodes = idx["nodes"]

    # Top-level nodes: parent_id is None (their parent is root, not a node)
    assert nodes[0].get("parent_id") is None
    assert nodes[1].get("parent_id") is None


# ------------------------------------------------------------------
# _flatten_index
# ------------------------------------------------------------------

def test_flatten_index_empty_returns_empty() -> None:
    result = _flatten_index({}, "/docs/file.txt")
    assert result == []


def test_flatten_index_preserves_content(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    segs = [
        _seg("alfa", "Texto del segmento alfa con contenido.", index=0),
        _seg("beta", "Texto del segmento beta con contenido.", index=1),
        _seg("gamma", "Texto del segmento gamma con contenido.", index=2),
    ]
    store.put(_doc(), segs)

    _, recovered = store.get("/docs/file.txt")
    all_content = " ".join(s.content for s in recovered)
    assert "alfa" in all_content
    assert "beta" in all_content
    assert "gamma" in all_content


def test_flatten_index_sets_file_path(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    store.put(_doc("/docs/target.txt"), [_seg("s1", "Contenido con path específico.")])

    _, recovered = store.get("/docs/target.txt")
    assert all(s.file_path == "/docs/target.txt" for s in recovered)


def test_flatten_index_roundtrip_segment_count(tmp_path: Path) -> None:
    store = CacheStore(tmp_path)
    n = 5
    segs = [_seg(f"s{i}", f"Bloque número {i} con suficiente texto.", index=i) for i in range(n)]
    store.put(_doc(), segs)

    _, recovered = store.get("/docs/file.txt")
    assert len(recovered) == n
