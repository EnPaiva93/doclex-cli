from __future__ import annotations

from pathlib import Path

from doclex.index.title_index import TitleIndex
from doclex.metadata.models import FileRecord, PassageResult, Snippet
from doclex.pipeline import _coverage, _document_score


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


# ------------------------------------------------------------------
# Rarity-weighted query coverage
# ------------------------------------------------------------------

def _passage_with(content: str, score: float) -> PassageResult:
    p = _passage(score)
    p.content = content
    return p


def test_coverage_rewards_matching_the_rare_term() -> None:
    """A page repeating a common word must not beat one holding the rare one."""
    weights = {"gt": 3.2, "dpm": 5.9, "que": 0.7}

    common = _coverage([_passage_with("GT/CAY y GT/CAY, que se aplica", 0)], weights)
    rare = _coverage([_passage_with("GT/DPM Departamento de Protecciones", 0)], weights)

    assert rare > common


def test_coverage_is_complete_when_every_term_appears() -> None:
    weights = {"vacaciones": 4.0, "dias": 2.0}
    passage = _passage_with("Son 15 dias de vacaciones por año.", 0)

    assert _coverage([passage], weights) == 1.0


def test_coverage_uses_the_document_best_passage() -> None:
    weights = {"gt": 3.2, "dpm": 5.9}
    passages = [
        _passage_with("Solo menciona GT aquí.", 0),
        _passage_with("Aquí aparece GT/DPM completo.", 0),
    ]

    assert _coverage(passages, weights) == 1.0


def test_coverage_without_usable_terms_does_not_penalise() -> None:
    assert _coverage([_passage_with("cualquier texto", 0)], {}) == 1.0
