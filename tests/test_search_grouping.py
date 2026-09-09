from __future__ import annotations

from doclex.metadata.models import PassageResult, Snippet
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
