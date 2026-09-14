from __future__ import annotations

import hashlib
import json
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

    Persisted alongside the segment index. Building one costs BM25X's one-time
    initialisation — 1.4s on the reference corpus, dwarfing the 20ms to load an
    index from disk — and the CLI runs a fresh process per search, so rebuilding
    every time would put that on every query. A fingerprint of the file table
    decides when the stored copy is stale.
    """

    def __init__(self, index_dir: Path | None = None) -> None:
        self._dir = index_dir
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

    def load(self, fingerprint: str) -> bool:
        """Restore a stored index, or report that it is missing or stale."""
        if self._dir is None or not self._meta_path.exists():
            return False
        try:
            meta = json.loads(self._meta_path.read_text(encoding="utf-8"))
            if meta.get("fingerprint") != fingerprint:
                return False
            self._bm25 = BM25.load(str(self._dir))
            self._file_ids = meta["file_ids"]
        except (OSError, ValueError, KeyError):
            return False
        return True

    def save(self, fingerprint: str) -> None:
        if self._dir is None or self._bm25 is None:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        self._bm25.save(str(self._dir))
        self._meta_path.write_text(
            json.dumps({"fingerprint": fingerprint, "file_ids": self._file_ids}),
            encoding="utf-8",
        )

    @property
    def _meta_path(self) -> Path:
        assert self._dir is not None
        return self._dir / "titles.json"

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


def fingerprint(files: list[FileRecord]) -> str:
    """Identify exactly the set of files a stored title index was built from."""
    joined = "\n".join(f"{f.id}:{f.path}" for f in sorted(files, key=lambda f: f.id or 0))
    return hashlib.sha256(joined.encode()).hexdigest()
