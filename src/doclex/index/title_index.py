from __future__ import annotations

from pathlib import Path

from bm25x import BM25

from doclex.metadata.models import FileRecord


class TitleIndex:
    """BM25 over file names and folders, scored separately from document bodies.

    A query term in the file name is strong evidence about what the whole
    document is for, which body text alone cannot express: a question like
    "cuantos días de vacaciones me corresponde" scores "corresponde" wherever
    it appears, while "VACACIONES ANUALES REMUNERADAS.pdf" says outright that
    the file is about the subject.

    Built in memory at startup rather than persisted: one entry per file, so
    even large corpora cost a few thousand short strings, and nothing can fall
    out of sync with the files table.
    """

    def __init__(self) -> None:
        self._bm25: BM25 | None = None
        self._file_ids: list[int] = []

    def build(self, files: list[FileRecord], root: Path | None = None) -> None:
        self._bm25 = BM25()
        self._file_ids = []

        titles: list[str] = []
        for record in files:
            if record.id is None:
                continue
            self._file_ids.append(record.id)
            titles.append(_title_of(record.path, root))

        if titles:
            self._bm25.add(titles)

    def search(self, query: str, k: int) -> dict[int, float]:
        """Return {file_id: score} for the best-matching titles."""
        if self._bm25 is None or not self._file_ids:
            return {}
        return {
            self._file_ids[doc_id]: float(score)
            for doc_id, score in self._bm25.search(query, k)
            if 0 <= doc_id < len(self._file_ids)
        }


def _title_of(path: str, root: Path | None) -> str:
    """Words a reader would use to name the file: its name plus its folders.

    Separators become spaces so "IPE-09 VACACIONES.pdf" and the folders above
    it tokenize the same way the query does.
    """
    file_path = Path(path)
    parts = [file_path.stem]
    if root:
        try:
            parts = list(file_path.relative_to(root).parts[:-1]) + parts
        except ValueError:
            pass
    return " ".join(parts).replace("-", " ").replace("_", " ")
