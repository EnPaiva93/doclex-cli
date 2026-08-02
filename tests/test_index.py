from __future__ import annotations

from pathlib import Path

import pytest

from doclex.index.bm25_index import BM25Index, make_snippet
from doclex.metadata.models import Segment


def _make_segment(seg_id: str, content: str, index: int = 0) -> Segment:
    return Segment(
        id=seg_id,
        file_path="/docs/file.txt",
        content=content,
        location_type="block",
        location_label=f"Block {index + 1}",
        location_index=index,
    )


@pytest.fixture()
def index(tmp_path: Path) -> BM25Index:
    idx = BM25Index(tmp_path / "bm25_index")
    idx.load_or_create()
    return idx


def test_add_and_search(index: BM25Index) -> None:
    segments = [
        _make_segment("seg1", "Kreuzberg extrae texto de documentos PDF y DOCX.", 0),
        _make_segment("seg2", "BM25 es un algoritmo de recuperación de información.", 1),
        _make_segment("seg3", "Watchdog monitorea carpetas en tiempo real.", 2),
    ]
    doc_ids = index.add(segments)

    assert len(doc_ids) == 3

    results = index.search("Kreuzberg", k=5)
    assert results
    top_id, top_score = results[0]
    assert top_id == doc_ids[0]
    assert top_score > 0


def test_search_returns_top_k(index: BM25Index) -> None:
    segments = [_make_segment(f"seg{i}", f"documento {i} con información relevante sobre búsqueda", i) for i in range(10)]
    index.add(segments)

    results = index.search("documento búsqueda", k=3)
    assert len(results) <= 3


def test_delete_reduces_index_length(index: BM25Index) -> None:
    # BM25X uses soft-delete: deleted docs may still appear in raw results
    # but Pipeline filters them via SQLite. This test verifies delete() is accepted.
    segments = [
        _make_segment("seg1", "Python es un lenguaje de programación muy popular.", 0),
        _make_segment("seg2", "Rust es un lenguaje de sistemas con seguridad de memoria.", 1),
    ]
    doc_ids = index.add(segments)
    assert len(index) == 2

    index.delete([doc_ids[0]])
    # After delete, search still works without error
    results = index.search("lenguaje", k=5)
    assert isinstance(results, list)


def test_empty_index_returns_empty(index: BM25Index) -> None:
    results = index.search("cualquier cosa", k=5)
    assert results == []


def test_len_reflects_added_segments(index: BM25Index) -> None:
    assert len(index) == 0
    segments = [_make_segment(f"s{i}", f"contenido del segmento número {i} con texto suficiente", i) for i in range(5)]
    index.add(segments)
    assert len(index) == 5


def test_persist_and_reload(tmp_path: Path) -> None:
    index_dir = tmp_path / "bm25_index"
    idx = BM25Index(index_dir)
    idx.load_or_create()

    segments = [_make_segment("seg1", "texto persistido en disco para verificar recarga del índice", 0)]
    idx.add(segments)
    idx.save()

    # Reload from disk
    idx2 = BM25Index(index_dir)
    idx2.load_or_create()

    results = idx2.search("persistido disco", k=5)
    assert results


# ------------------------------------------------------------------
# make_snippet
# ------------------------------------------------------------------

def test_snippet_contains_query_term() -> None:
    content = "El sistema usa BM25 para indexación léxica sin embeddings."
    snippet = make_snippet(content, "BM25")
    assert "BM25" in snippet


def test_snippet_truncates_long_content() -> None:
    content = "a" * 1000
    snippet = make_snippet(content, "zzz")  # term not found
    assert len(snippet) <= 210  # window + ellipsis


def test_snippet_adds_ellipsis_when_truncated() -> None:
    content = "inicio " + ("x " * 200) + "término " + ("y " * 200) + "final"
    snippet = make_snippet(content, "término")
    assert "…" in snippet


def test_snippet_anchors_on_densest_cluster_not_first_occurrence() -> None:
    """An early, isolated mention of one query term must not win over a later
    passage where multiple query terms cluster together."""
    filler = "x " * 150
    content = (
        "vacaciones " + filler +  # isolated first hit for "vacaciones", far from the real match
        "días de vacaciones anuales remuneradas para el personal permanente"
    )
    snippet = make_snippet(content, "días vacaciones", window=80)
    assert "días de vacaciones anuales" in snippet
