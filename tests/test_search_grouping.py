from __future__ import annotations

from pathlib import Path

from doclex.index.title_index import TitleIndex
from doclex.metadata.models import FileRecord, PassageResult, Snippet
from doclex.pipeline import _document_score


def _passage(score: float) -> PassageResult:
    return PassageResult(
        segment_id="s",
        score=score,
        location_type="section",
        location_label="Section",
        location_index=0,
        snippet=Snippet(text=""),
        content="",
    )


def test_document_score_is_led_by_its_best_passage() -> None:
    assert _document_score([_passage(5.0)]) == 5.0


def test_extra_passages_add_less_than_the_best_one() -> None:
    """Coverage is rewarded, but a long document cannot win on volume alone."""
    one_strong = _document_score([_passage(10.0)])
    many_weak = _document_score([_passage(4.0), _passage(4.0), _passage(4.0)])

    assert one_strong > many_weak


def test_document_score_ignores_passages_beyond_the_weighted_ones() -> None:
    three = _document_score([_passage(5.0), _passage(4.0), _passage(3.0)])
    five = _document_score(
        [_passage(5.0), _passage(4.0), _passage(3.0), _passage(3.0), _passage(3.0)]
    )

    assert three == five


# ------------------------------------------------------------------
# Title index
# ------------------------------------------------------------------

def _file(file_id: int, path: str) -> FileRecord:
    return FileRecord(
        id=file_id, path=path, hash="h", mtime=0.0, size=1,
        mime_type="application/pdf", status="indexed",
    )


def test_title_index_matches_on_file_name() -> None:
    index = TitleIndex()
    index.build([
        _file(1, "/docs/IPE-09 VACACIONES ANUALES REMUNERADAS.pdf"),
        _file(2, "/docs/IPE-43 LIQUIDACION DE SUELDOS.pdf"),
    ])

    scores = index.search("vacaciones", 5)

    assert scores.get(1, 0) > scores.get(2, 0)


def test_title_index_matches_on_containing_folders() -> None:
    """A folder name describes what is inside it as surely as a file name does."""
    root = Path("/docs")
    index = TitleIndex()
    index.build([
        _file(1, "/docs/vacaciones/Formulario 12.pdf"),
        _file(2, "/docs/sueldos/Formulario 13.pdf"),
    ], root)

    scores = index.search("vacaciones", 5)

    assert scores.get(1, 0) > scores.get(2, 0)


def test_title_index_is_empty_without_files() -> None:
    index = TitleIndex()
    index.build([])

    assert index.search("cualquier cosa", 5) == {}
