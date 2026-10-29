from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path


class Config:
    """Where a project's data lives and how the engine behaves.

    Built from explicit arguments so the engine never reads the environment on
    its own; clients that want environment overrides use `from_env`.
    """

    def __init__(
        self,
        folder: Path | str,
        *,
        cache_dir: Path | str | None = None,
        db_path: Path | str | None = None,
        top_k: int = 10,
        debounce_secs: float = 1.0,
    ) -> None:
        self.folder = Path(folder).expanduser().resolve()
        if not self.folder.is_dir():
            raise ValueError(f"Not a directory: {self.folder}")

        self.cache_dir = (
            Path(cache_dir).expanduser().resolve()
            if cache_dir
            else self.folder / ".doclex"
        )
        self.db_path = (
            Path(db_path).expanduser().resolve()
            if db_path
            else self.cache_dir / "doclex.db"
        )

        self.bm25_index_dir = self.cache_dir / "bm25_index"
        self.title_index_dir = self.cache_dir / "title_index"

        self.top_k = top_k
        self.debounce_secs = debounce_secs

    @classmethod
    def from_env(
        cls,
        folder: Path | str | None = None,
        environ: Mapping[str, str] = os.environ,
    ) -> Config:
        """Build a config from DOCLEX_* variables.

        `folder` takes precedence over DOCLEX_FOLDER, so a client that resolves
        the folder itself (from a registered project) still honours the other
        overrides such as DOCLEX_CACHE_DIR.
        """
        folder = folder or environ.get("DOCLEX_FOLDER")
        if not folder:
            raise ValueError("A folder is required (argument or DOCLEX_FOLDER)")

        return cls(
            folder,
            cache_dir=environ.get("DOCLEX_CACHE_DIR"),
            db_path=environ.get("DOCLEX_DB_PATH"),
            top_k=int(environ.get("DOCLEX_TOP_K", "10")),
            debounce_secs=float(environ.get("DOCLEX_DEBOUNCE", "1.0")),
        )

    def ensure_dirs(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".pdf", ".txt", ".md", ".docx", ".xlsx", ".csv"}
)
